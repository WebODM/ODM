#!/usr/bin/env python
#******************************************************************************
#  $Id$
#
#  Project:  GDAL Python Interface
#  Purpose:  Script to merge greyscale as intensity into an RGB(A) image, for
#            instance to apply hillshading to a dem colour relief.
#  Author:   Frank Warmerdam, warmerdam@pobox.com
#            Trent Hare (USGS)
#            Modified by Piero Toffanin
#
#******************************************************************************
#  Copyright (c) 2009, Frank Warmerdam
#  Copyright (c) 2010, Even Rouault <even dot rouault at mines-paris dot org>
#
#  Permission is hereby granted, free of charge, to any person obtaining a
#  copy of this software and associated documentation files (the "Software"),
#  to deal in the Software without restriction, including without limitation
#  the rights to use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of the Software, and to permit persons to whom the
#  Software is furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included
#  in all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
#  OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
#  THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#******************************************************************************

import sys

import numpy
import rasterio
from rasterio.windows import Window

# =============================================================================
# rgb_to_hsv()
#
# rgb comes in as [r,g,b] with values in the range [0,255].  The returned
# hsv values will be with hue and saturation in the range [0,1] and value
# in the range [0,255]
#
def rgb_to_hsv( r,g,b ):

    maxc = numpy.maximum(r,numpy.maximum(g,b))
    minc = numpy.minimum(r,numpy.minimum(g,b))

    v = maxc

    minc_eq_maxc = numpy.equal(minc,maxc)

    # compute the difference, but reset zeros to ones to avoid divide by zeros later.
    ones = numpy.ones((r.shape[0],r.shape[1]))
    maxc_minus_minc = numpy.choose( minc_eq_maxc, (maxc-minc,ones) )

    s = (maxc-minc) / numpy.maximum(ones,maxc)
    rc = (maxc-r) / maxc_minus_minc
    gc = (maxc-g) / maxc_minus_minc
    bc = (maxc-b) / maxc_minus_minc

    maxc_is_r = numpy.equal(maxc,r)
    maxc_is_g = numpy.equal(maxc,g)
    maxc_is_b = numpy.equal(maxc,b)

    h = numpy.zeros((r.shape[0],r.shape[1]))
    h = numpy.choose( maxc_is_b, (h,4.0+gc-rc) )
    h = numpy.choose( maxc_is_g, (h,2.0+rc-bc) )
    h = numpy.choose( maxc_is_r, (h,bc-gc) )

    h = numpy.mod(h/6.0,1.0)

    hsv = numpy.asarray([h,s,v])

    return hsv

# =============================================================================
# hsv_to_rgb()
#
# hsv comes in as [h,s,v] with hue and saturation in the range [0,1],
# but value in the range [0,255].

def hsv_to_rgb( hsv ):

    h = hsv[0]
    s = hsv[1]
    v = hsv[2]

    #if s == 0.0: return v, v, v
    i = (h*6.0).astype(int)
    f = (h*6.0) - i
    p = v*(1.0 - s)
    q = v*(1.0 - s*f)
    t = v*(1.0 - s*(1.0-f))

    r = i.choose( v, q, p, p, t, v )
    g = i.choose( t, v, v, q, p, p )
    b = i.choose( p, p, t, v, v, q )

    rgb = numpy.asarray([r,g,b]).astype(numpy.uint8)

    return rgb

# =============================================================================
# Usage()

def Usage():
    print("""Usage: hsv_merge.py [-q] [-of format] src_color src_greyscale dst_color

where src_color is a RGB or RGBA dataset,
      src_greyscale is a greyscale dataset (e.g. the result of gdaldem hillshade)
      dst_color will be a RGB or RGBA dataset using the greyscale as the
      intensity for the color dataset.
""")
    sys.exit(1)

# =============================================================================
# 	Mainline
# =============================================================================

format = 'GTiff'
src_color_filename = None
src_greyscale_filename = None
dst_color_filename = None
quiet = False

i = 1
while i < len(sys.argv):
    arg = sys.argv[i]

    if arg == '-of':
        i = i + 1
        format = sys.argv[i]

    elif arg == '-q' or arg == '-quiet':
        quiet = True

    elif src_color_filename is None:
        src_color_filename = sys.argv[i]

    elif src_greyscale_filename is None:
        src_greyscale_filename = sys.argv[i]

    elif dst_color_filename is None:
        dst_color_filename = sys.argv[i]
    else:
        Usage()

    i = i + 1

if dst_color_filename is None:
    Usage()

with rasterio.open(src_greyscale_filename) as hilldataset, \
     rasterio.open(src_color_filename) as colordataset:

    if colordataset.count not in (3, 4):
        print('Source image does not appear to have three or four bands as required.')
        sys.exit(1)

    if colordataset.height != hilldataset.height or colordataset.width != hilldataset.width:
        print('Color and hillshade must be the same size in pixels.')
        sys.exit(1)

    hillbandnodatavalue = hilldataset.nodata

    profile = colordataset.profile.copy()
    profile.update(
        driver=format,
        dtype='uint8',
        crs=hilldataset.crs,
        transform=hilldataset.transform,
    )

    with rasterio.open(dst_color_filename, 'w', **profile) as outdataset:
        for i in range(hilldataset.height):
            win = Window(0, i, hilldataset.width, 1)

            rgb = colordataset.read([1, 2, 3], window=win)
            hillScanline = hilldataset.read(1, window=win)

            hsv = rgb_to_hsv(rgb[0], rgb[1], rgb[2])

            if hillbandnodatavalue is not None:
                equal_to_nodata = numpy.equal(hillScanline, hillbandnodatavalue)
                v = numpy.choose(equal_to_nodata, (hillScanline, hsv[2]))
            else:
                v = hillScanline

            hsv_adjusted = numpy.asarray([hsv[0], hsv[1], v])
            dst_color = hsv_to_rgb(hsv_adjusted)

            outdataset.write(dst_color, [1, 2, 3], window=win)
            if colordataset.count == 4:
                aScanline = colordataset.read(4, window=win)
                outdataset.write(aScanline, 4, window=win)

        if not quiet:
            print()
