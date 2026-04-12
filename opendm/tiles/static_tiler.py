#!/usr/bin/env python3
"""
conv2tiles.py - Generate XYZ or TMS tiles from a GeoTIFF.
Author: Piero Toffanin

Usage:
    python conv2tiles.py input.tif [output_dir] [options]

Options:
    -z, --zoom       Zoom level(s): single "N", range "min-max", or "auto" (default: auto)
    -x               Tile x coordinate (must be used with -y)
    -y               Tile y coordinate (must be used with -x)
    -s, --size       Tile size in pixels (default: 256, must be power of 2)
    --tms            Use TMS tile numbering instead of XYZ
    -f, --format     Output format: text or json (default: text)
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from PIL import Image


class GlobalMercator:
    def __init__(self, tile_size: int = 256):
        self.tile_size = tile_size
        self.origin_shift = 2.0 * math.pi * 6378137.0 / 2.0
        self.initial_resolution = 2.0 * math.pi * 6378137.0 / tile_size
        self.max_zoom_level = 99

    def resolution(self, zoom: int) -> float:
        """Meters/pixel for a given zoom level (at equator)."""
        return self.initial_resolution / (2 ** zoom)

    def pixels_to_meters(self, px: int, py: int, zoom: int):
        """Convert pixel coordinates at a zoom level to EPSG:3857 meters."""
        res = self.resolution(zoom)
        mx = px * res - self.origin_shift
        my = py * res - self.origin_shift
        return mx, my

    def meters_to_pixels(self, mx: float, my: float, zoom: int):
        """Convert EPSG:3857 meters to pixel coordinates at a zoom level."""
        res = self.resolution(zoom)
        px = (mx + self.origin_shift) / res
        py = (my + self.origin_shift) / res
        return px, py

    def pixels_to_tile(self, px: float, py: float):
        """Return the tile covering a given pixel coordinate."""
        tx = int(math.ceil(px / self.tile_size) - 1)
        ty = int(math.ceil(py / self.tile_size) - 1)
        return tx, ty

    def meters_to_tile(self, mx: float, my: float, zoom: int):
        """Return the tile covering a given mercator coordinate."""
        px, py = self.meters_to_pixels(mx, my, zoom)
        return self.pixels_to_tile(px, py)

    def tile_bounds(self, tx: int, ty: int, zoom: int):
        """Return the EPSG:3857 bounding box of a tile (min_x, min_y, max_x, max_y)."""
        min_x, min_y = self.pixels_to_meters(tx * self.tile_size, ty * self.tile_size, zoom)
        max_x, max_y = self.pixels_to_meters((tx + 1) * self.tile_size, (ty + 1) * self.tile_size, zoom)
        return min_x, min_y, max_x, max_y

    def zoom_for_pixel_size(self, pixel_size: float) -> int:
        """Return the maximal zoom level where pixel_size > resolution."""
        for i in range(self.max_zoom_level):
            if pixel_size > self.resolution(i):
                return max(0, i - 1)
        return 0


class StaticTiler:
    def __init__(self, input_path: str, output_folder: str,
                 tile_size: int = 256, tms: bool = False):
        self.input_path = input_path
        self.output_folder = output_folder
        self.tile_size = tile_size
        self.tms = tms
        self.mercator = GlobalMercator(tile_size)

        if not os.path.isfile(input_path):
            raise FileNotFoundError(f"{input_path} does not exist")

        if tile_size <= 0 or (tile_size & (tile_size - 1)) != 0:
            raise ValueError("Tile size must be a power of 2 greater than 0")

        if output_folder:
            os.makedirs(output_folder, exist_ok=True)

        self._src = rasterio.open(input_path)

        if self._src.crs is None:
            raise RuntimeError(f"No projection found in {input_path}")
        if self._src.transform.is_identity:
            raise RuntimeError(f"{input_path} is not georeferenced")

        # Warp to EPSG:3857 if needed
        if self._src.crs.to_epsg() != 3857:
            self._vrt = WarpedVRT(self._src, crs="EPSG:3857",
                                  resampling=Resampling.nearest)
            self._ds = self._vrt
        else:
            self._vrt = None
            self._ds = self._src

        self.n_bands = self._count_data_bands()

        gt = self._ds.transform
        if abs(gt.a) < 1e-15 or abs(gt.e) < 1e-15:
            raise RuntimeError("Invalid geotransform: pixel size is zero")

        w = self._ds.width
        h = self._ds.height

        # Bounds in EPSG:3857 meters
        self.o_min_x = gt.c
        self.o_max_x = gt.c + w * gt.a
        self.o_max_y = gt.f
        self.o_min_y = gt.f + h * gt.e  # gt.e is negative

        pixel_size = gt.a  # meters/pixel in x at EPSG:3857

        self.t_max_z = self.mercator.zoom_for_pixel_size(pixel_size)
        self.t_min_z = self.mercator.zoom_for_pixel_size(
            pixel_size * max(w, h) / self.tile_size
        )

    def _count_data_bands(self) -> int:
        """Count non-alpha data bands."""
        total = self._ds.count
        # Check if the last band is alpha
        if total >= 2:
            ci = self._ds.colorinterp
            if ci[-1] == rasterio.enums.ColorInterp.alpha:
                return total - 1
            # Also treat 4- and 2-band as having alpha
            if total == 4 or total == 2:
                return total - 1
        return total

    def _find_alpha_band_index(self):
        """Return the 1-based index of the alpha band, or None."""
        for i, ci in enumerate(self._ds.colorinterp, start=1):
            if ci == rasterio.enums.ColorInterp.alpha:
                return i
        return None

    @staticmethod
    def _xyz_to_tms(ty: int, tz: int) -> int:
        return (2 ** tz - 1) - ty

    @staticmethod
    def _tms_to_xyz(ty: int, tz: int) -> int:
        return (2 ** tz - 1) - ty

    def _get_tile_path(self, z: int, x: int, y: int) -> str:
        d = os.path.join(self.output_folder, str(z), str(x))
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{y}.png")

    def _geo_query(self, ulx: float, uly: float, lrx: float, lry: float,
                   query_size: int = 0):
        """
        Map a mercator bbox to pixel read/write windows (with border clamping).

        Returns (r_x, r_y, r_xsize, r_ysize, w_x, w_y, w_xsize, w_ysize).
        """
        gt = self._ds.transform

        r_x = int((ulx - gt.c) / gt.a + 0.001)
        r_y = int((uly - gt.f) / gt.e + 0.001)
        r_xsize = int((lrx - ulx) / gt.a + 0.5)
        r_ysize = int((lry - uly) / gt.e + 0.5)

        if query_size == 0:
            w_xsize = r_xsize
            w_ysize = r_ysize
        else:
            w_xsize = query_size
            w_ysize = query_size

        w_x = 0
        if r_x < 0:
            rx_shift = abs(r_x)
            if r_xsize > 0:
                w_x = int(w_xsize * (rx_shift / r_xsize))
                w_xsize -= w_x
                r_xsize -= int(r_xsize * (rx_shift / r_xsize))
            r_x = 0

        raster_x = self._ds.width
        raster_y = self._ds.height

        if r_x + r_xsize > raster_x:
            if r_xsize > 0:
                w_xsize = int(w_xsize * ((raster_x - r_x) / r_xsize))
            r_xsize = raster_x - r_x

        w_y = 0
        if r_y < 0:
            ry_shift = abs(r_y)
            if r_ysize > 0:
                w_y = int(w_ysize * (ry_shift / r_ysize))
                w_ysize -= w_y
                r_ysize -= int(r_ysize * (ry_shift / r_ysize))
            r_y = 0

        if r_y + r_ysize > raster_y:
            if r_ysize > 0:
                w_ysize = int(w_ysize * ((raster_y - r_y) / r_ysize))
            r_ysize = raster_y - r_y

        return r_x, r_y, r_xsize, r_ysize, w_x, w_y, w_xsize, w_ysize

    def get_min_max_z(self):
        return self.t_min_z, self.t_max_z

    def get_tiles_for_zoom(self, tz: int):
        """Return list of (tx, ty, tz) for a given zoom level."""
        min_tile = self.mercator.meters_to_tile(self.o_min_x, self.o_min_y, tz)
        max_tile = self.mercator.meters_to_tile(self.o_max_x, self.o_max_y, tz)

        min_tx = max(0, min_tile[0])
        max_tx = min(2 ** tz - 1, max_tile[0])

        tiles = []
        for ty in range(min_tile[1], max_tile[1] + 1):
            for tx in range(min_tx, max_tx + 1):
                out_ty = self._xyz_to_tms(ty, tz) if self.tms else ty
                tiles.append((tx, out_ty, tz))
        return tiles

    def tile(self, tz: int, tx: int, ty: int) -> str:
        """Generate a single tile and return its file path."""
        tile_path = self._get_tile_path(tz, tx, ty)

        # Internally always work in XYZ (TMS origin at bottom)
        work_ty = self._tms_to_xyz(ty, tz) if self.tms else ty

        # Tile bounds in EPSG:3857 meters
        b_min_x, b_min_y, b_max_x, b_max_y = self.mercator.tile_bounds(tx, work_ty, tz)

        query_size = self.tile_size
        r_x, r_y, r_xsize, r_ysize, w_x, w_y, w_xsize, w_ysize = \
            self._geo_query(b_min_x, b_max_y, b_max_x, b_min_y, query_size)

        if r_xsize == 0 or r_ysize == 0 or w_xsize == 0 or w_ysize == 0:
            # Empty / out-of-bounds tile – write a transparent PNG
            img = Image.new("RGBA", (self.tile_size, self.tile_size), (0, 0, 0, 0))
            img.save(tile_path, "PNG")
            return tile_path

        capped_bands = min(3, self.n_bands)
        band_indices = list(range(1, capped_bands + 1))

        # Read data bands
        window = rasterio.windows.Window(r_x, r_y, r_xsize, r_ysize)
        data = self._ds.read(
            band_indices, window=window,
            out_shape=(capped_bands, w_ysize, w_xsize),
            resampling=Resampling.nearest
        )

        dtype = self._ds.dtypes[0]

        # Rescale non-byte data to 0-255
        if dtype != "uint8":
            # Compute global min/max across all data bands using dataset statistics
            if not hasattr(self, "_global_min"):
                self._global_min = float("inf")
                self._global_max = float("-inf")
                for b in band_indices:
                    stats = self._src.statistics(b)
                    self._global_min = min(self._global_min, stats.min)
                    self._global_max = max(self._global_max, stats.max)

                if self._global_min == self._global_max:
                    self._global_max += 0.1

            delta = self._global_max - self._global_min
            data = data.astype(np.float64)
            data = np.clip(data, self._global_min, self._global_max)
            data = ((data - self._global_min) / delta * 255.0).astype(np.uint8)
        else:
            data = data.astype(np.uint8)

        # Read alpha
        alpha_idx = self._find_alpha_band_index()
        if alpha_idx is not None:
            alpha = self._ds.read(
                alpha_idx, window=window,
                out_shape=(w_ysize, w_xsize),
                resampling=Resampling.nearest
            ).astype(np.uint8)
        else:
            # Use the mask band (0 = nodata, 255 = valid)
            mask = self._ds.read_masks(
                1, window=window,
                out_shape=(w_ysize, w_xsize)
            ).astype(np.uint8)
            alpha = mask

        # Compose RGBA tile image
        tile_img = np.zeros((self.tile_size, self.tile_size, 4), dtype=np.uint8)

        if capped_bands == 1:
            # Grayscale --> RGB
            for c in range(3):
                tile_img[w_y:w_y + w_ysize, w_x:w_x + w_xsize, c] = data[0]
        else:
            for c in range(capped_bands):
                tile_img[w_y:w_y + w_ysize, w_x:w_x + w_xsize, c] = data[c]

        tile_img[w_y:w_y + w_ysize, w_x:w_x + w_xsize, 3] = alpha

        img = Image.fromarray(tile_img, "RGBA")
        img.save(tile_path, "PNG")
        return tile_path

    def close(self):
        if self._vrt is not None:
            self._vrt.close()
        self._src.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def parse_zoom_range(z_str: str):
    """Parse a zoom string: 'N', 'min-max', or 'auto'."""
    if "-" in z_str:
        parts = z_str.split("-", 1)
        lo, hi = int(parts[0]), int(parts[1])
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi
    return int(z_str), int(z_str)


def main():
    parser = argparse.ArgumentParser(
        description="Generate XYZ/TMS tiles from a GeoTIFF."
    )
    parser.add_argument("input", help="Path to input GeoTIFF")
    parser.add_argument("output", nargs="?", default=None,
                        help="Output directory (default: <input>_tiles/)")
    parser.add_argument("-z", "--zoom", default="auto",
                        help="Zoom levels: 'N', 'min-max', or 'auto' (default: auto)")
    parser.add_argument("-x", default="auto",
                        help="Tile x coordinate (use with -y)")
    parser.add_argument("-y", default="auto",
                        help="Tile y coordinate (use with -x)")
    parser.add_argument("-s", "--size", type=int, default=256,
                        help="Tile size in pixels (default: 256)")
    parser.add_argument("--tms", action="store_true",
                        help="Generate TMS tiles instead of XYZ")
    parser.add_argument("-f", "--format", default="text", choices=["text", "json"],
                        help="Output list format (default: text)")
    args = parser.parse_args()

    output = args.output
    if output is None:
        output = Path(args.input).stem + "_tiles"

    with StaticTiler(args.input, output, args.size, args.tms) as tiler:
        if args.zoom == "auto":
            z_min, z_max = tiler.get_min_max_z()
        else:
            z_min, z_max = parse_zoom_range(args.zoom)

        results = []

        for z in range(z_min, z_max + 1):
            if args.x != "auto" and args.y != "auto":
                path = tiler.tile(z, int(args.x), int(args.y))
                results.append(path)
            else:
                tiles = tiler.get_tiles_for_zoom(z)
                for tx, ty, tz in tiles:
                    path = tiler.tile(tz, tx, ty)
                    results.append(path)

        if args.format == "json":
            print(json.dumps(results))
        else:
            for r in results:
                print(r)


if __name__ == "__main__":
    main()
