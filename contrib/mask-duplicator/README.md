# Semi-automated Masking for 360 images

For usage with 360 images and ODX to mask out the tripod/user/camera mount. 360 models in ODX can be made from 360 images, but unless you mask out the camera mount there will be repeated artifacts along the camera path. ODX supports image masking but requires a mask for each image. Since the 360 camera is generally on a fixed mount (bike helmet, moving tripod, etc), you can make one mask and then duplicate this for all images, but this is tedious to do by hand.

This snippet takes the file path of a single image mask and duplicates it for all images in the dataset. After creating the masks, process the original images and the masks together in ODX you'll get a clean model with the camera mount artifacts eliminated.

Before using this code snippet, open one of your 360 images in an image editor and mask out the helmet or tripod, etc at the bottom of your image. Save this image as a png and then use it as the mask image that will be duplicated for all images in the dataset.

See https://docs.webodm.org/tutorials/using-image-masks/ for more details on mask creation.
