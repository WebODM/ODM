from opendm import context
from opendm.system import run
from opendm import log
from opendm.point_cloud import export_summary_json
from osgeo import ogr
import fiona
import fiona.crs
import json, os
from opendm.concurrency import get_max_memory
from opendm.utils import double_quote

class Cropper:
    def __init__(self, storage_dir, files_prefix = "crop"):
        self.storage_dir = storage_dir
        self.files_prefix = files_prefix

    def path(self, suffix):
        """
        @return a path relative to storage_dir and prefixed with files_prefix
        """
        return os.path.join(self.storage_dir, '{}.{}'.format(self.files_prefix, suffix))

    @staticmethod
    def crop(gpkg_path, geotiff_path, gdal_options, keep_original=True, warp_options=[]):
        if not os.path.exists(gpkg_path) or not os.path.exists(geotiff_path):
            log.ODM_WARNING("Either {} or {} does not exist, will skip cropping.".format(gpkg_path, geotiff_path))
            return geotiff_path

        log.ODM_INFO("Cropping %s" % geotiff_path)

        # Rename original file
        # path/to/odm_orthophoto.tif --> path/to/odm_orthophoto.original.tif
        
        path, filename = os.path.split(geotiff_path)
        # path = path/to
        # filename = odm_orthophoto.tif

        basename, ext = os.path.splitext(filename)
        # basename = odm_orthophoto
        # ext = .tif

        original_geotiff = os.path.join(path, "{}.original{}".format(basename, ext))
        os.replace(geotiff_path, original_geotiff)

        try:
            kwargs = {
                'gpkg_path': double_quote(gpkg_path),
                'geotiffInput': double_quote(original_geotiff),
                'geotiffOutput': double_quote(geotiff_path),
                'options': ' '.join(map(lambda k: '-co {}={}'.format(k, gdal_options[k]), gdal_options)),
                'warpOptions': ' '.join(warp_options),
                'max_memory': get_max_memory()
            }

            run('gdalwarp -cutline {gpkg_path} '
                '-crop_to_cutline '
                '{options} '
                '{warpOptions} '
                '{geotiffInput} '
                '{geotiffOutput} '
                '--config GDAL_CACHEMAX {max_memory}%'.format(**kwargs))

            if not keep_original:
                os.remove(original_geotiff)

        except Exception as e:
            log.ODM_WARNING('Something went wrong while cropping: {}'.format(e))
            
            # Revert rename
            os.replace(original_geotiff, geotiff_path)

        return geotiff_path

    @staticmethod
    def merge_bounds(input_bound_files, output_bounds, buffer_distance = 0):
        """
        Merge multiple bound files into a single bound computed from the convex hull
        of all bounds (minus a buffer distance in meters)
        """
        geomcol = ogr.Geometry(ogr.wkbGeometryCollection)

        driver = ogr.GetDriverByName('GPKG')
        srs = None

        for input_bound_file in input_bound_files:
            ds = driver.Open(input_bound_file, 0) # ready-only

            layer = ds.GetLayer()
            srs = layer.GetSpatialRef()

            # Collect all Geometry
            for feature in layer:
                geomcol.AddGeometry(feature.GetGeometryRef())
            
            ds = None

        # Calculate convex hull
        convexhull = geomcol.ConvexHull()

        # If buffer distance is specified
        # Create two buffers, one shrunk by
        # N + 3 and then that buffer expanded by 3
        # so that we get smooth corners. \m/
        BUFFER_SMOOTH_DISTANCE = 3

        if buffer_distance > 0:
            convexhull = convexhull.Buffer(-(buffer_distance + BUFFER_SMOOTH_DISTANCE))
            convexhull = convexhull.Buffer(BUFFER_SMOOTH_DISTANCE)

        # Save to a new file
        if os.path.exists(output_bounds):
            driver.DeleteDataSource(output_bounds)

        out_ds = driver.CreateDataSource(output_bounds)
        layer = out_ds.CreateLayer("convexhull", srs=srs, geom_type=ogr.wkbPolygon)

        feature_def = layer.GetLayerDefn()
        feature = ogr.Feature(feature_def)
        feature.SetGeometry(convexhull)
        layer.CreateFeature(feature)
        feature = None

        # Save and close output data source
        out_ds = None

    def create_bounds_geojson(self, pointcloud_path, buffer_distance = 0, decimation_step=40, edge_length=1.0, pc_wkt="EPSG:4326"):
        """
        Compute a buffered polygon around the data extents (not just a bounding box)
        of the given point cloud.

        @return filename to GeoJSON containing the polygon
        """
        if not os.path.exists(pointcloud_path):
            log.ODM_WARNING('Point cloud does not exist, cannot generate bounds {}'.format(pointcloud_path))
            return ''

        # Do decimation prior to extracting boundary information
        decimated_pointcloud_path = self.path('decimated.las')

        run("pdal translate -i \"{}\" "
            "-o \"{}\" "
            "decimation "
            "--filters.decimation.step={} ".format(pointcloud_path, decimated_pointcloud_path, decimation_step))

        if not os.path.exists(decimated_pointcloud_path):
            log.ODM_WARNING('Could not decimate point cloud, thus cannot generate GPKG bounds {}'.format(decimated_pointcloud_path))
            return ''

        # Use PDAL to dump boundary information
        tmp_bounds_geojson_path = self.path('tmp-bounds.geojson')
        if os.path.isfile(tmp_bounds_geojson_path):
            os.unlink(tmp_bounds_geojson_path)

        run('pdal tindex create --tindex {0} -f GeoJSON --threshold 1 --resolution {1} --t_srs={2} --filespec {3}'.format(
                        double_quote(tmp_bounds_geojson_path), 
                        edge_length, 
                        double_quote(pc_wkt), 
                        double_quote(decimated_pointcloud_path)))
    
        if not os.path.isfile(tmp_bounds_geojson_path): 
            raise RuntimeError("Could not determine point cloud boundaries")

        # Create a convex hull around the boundary
        # as to encompass the entire area (no holes)    
        driver = ogr.GetDriverByName('GeoJSON')
        ds = driver.Open(tmp_bounds_geojson_path, 0) # ready-only
        layer = ds.GetLayer()

        # Collect all Geometry
        geomcol = ogr.Geometry(ogr.wkbGeometryCollection)
        for feature in layer:
            geomcol.AddGeometry(feature.GetGeometryRef())

        # Calculate convex hull
        convexhull = geomcol.ConvexHull()

        # If buffer distance is specified
        # Create two buffers, one shrunk by
        # N + 3 and then that buffer expanded by 3
        # so that we get smooth corners. \m/
        BUFFER_SMOOTH_DISTANCE = 3

        if buffer_distance > 0:
            # For small areas, check that buffering doesn't obliterate 
            # our hull
            tmp = convexhull.Buffer(-(buffer_distance + BUFFER_SMOOTH_DISTANCE))
            tmp = tmp.Buffer(BUFFER_SMOOTH_DISTANCE)
            if tmp.Area() > 0:
                convexhull = tmp
            else:
                log.ODM_WARNING("Very small crop area detected, we will not smooth it.")

        # Save to a new file
        bounds_geojson_path = self.path('bounds.geojson')
        if os.path.exists(bounds_geojson_path):
            os.remove(bounds_geojson_path)

        out_ds = driver.CreateDataSource(bounds_geojson_path)
        srs = ogr.osr.SpatialReference()
        srs.ImportFromWkt(pc_wkt)
        layer = out_ds.CreateLayer("convexhull", srs=srs, geom_type=ogr.wkbPolygon)

        feature_def = layer.GetLayerDefn()
        feature = ogr.Feature(feature_def)
        feature.SetGeometry(convexhull)
        layer.CreateFeature(feature)
        feature = None

        # Save and close data sources
        out_ds = ds = None

        # Remove decimated point cloud
        if os.path.exists(decimated_pointcloud_path):
            os.remove(decimated_pointcloud_path)
        
        # Remove tmp bounds
        if os.path.exists(tmp_bounds_geojson_path):
            os.remove(tmp_bounds_geojson_path)

        return bounds_geojson_path


    def create_bounds_gpkg(self, pointcloud_path, buffer_distance = 0, decimation_step=40):
        """
        Compute a buffered polygon around the data extents (not just a bounding box)
        of the given point cloud.
        
        @return filename to Geopackage containing the polygon
        """
        if not os.path.exists(pointcloud_path):
            log.ODM_WARNING('Point cloud does not exist, cannot generate GPKG bounds {}'.format(pointcloud_path))
            return ''


        summary_file_path = os.path.join(self.storage_dir, '{}.summary.json'.format(self.files_prefix))
        export_summary_json(pointcloud_path, summary_file_path)
        
        pc_wkt = None
        edge_length = 1.0
        with open(summary_file_path, 'r') as f:
            json_f = json.loads(f.read())
            pc_wkt = json_f['summary']['srs']['wkt']

        if pc_wkt is None: raise RuntimeError("Could not determine point cloud WKT declaration")

        bounds_geojson_path = self.create_bounds_geojson(pointcloud_path, buffer_distance, decimation_step, edge_length=edge_length, pc_wkt=pc_wkt)
        bounds_gpkg_path = os.path.join(self.storage_dir, '{}.bounds.gpkg'.format(self.files_prefix))

        if os.path.isfile(bounds_gpkg_path):
            os.remove(bounds_gpkg_path)

        # Convert bounds to GPKG
        with fiona.open(bounds_geojson_path, 'r') as src:
            with fiona.open(bounds_gpkg_path, 'w', driver='GPKG',
                            crs=fiona.crs.from_string(pc_wkt),
                            schema=src.schema) as dst:
                for feature in src:
                    dst.write(feature)

        return bounds_gpkg_path

