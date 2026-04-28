import os

from opendm import io
from opendm import log
from opendm import types
from opendm.utils import copy_paths, get_processing_results_paths
from opendm.ogctiles import build_3dtiles
from opendm.gltf import obj2glb

class ODMPostProcess(types.ODM_Stage):
    def process(self, args, outputs):
        tree = outputs['tree']
        reconstruction = outputs['reconstruction']

        log.INFO("Post Processing")

        if args.gltf:
            textured_model = os.path.join(tree.odm_texturing, tree.odm_textured_model_obj)
            textured_model_25d = os.path.join(tree.odm_25dtexturing, tree.odm_textured_model_obj)
            
            if os.path.isfile(textured_model) and not args.skip_3dmodel:
                input_obj = textured_model
            elif os.path.isfile(textured_model_25d):
                input_obj = textured_model_25d
            else:
                input_obj = textured_model
            
            odm_textured_model_glb = os.path.join(os.path.dirname(input_obj), tree.odm_textured_model_glb)

            if not os.path.exists(odm_textured_model_glb) or self.rerun():
                log.INFO("Generating glTF Binary")
                try:
                    obj2glb(input_obj, odm_textured_model_glb, rtc=reconstruction.get_proj_offset(), _info=log.INFO)
                except Exception as e:
                    log.WARNING(str(e))

        if getattr(args, '3d_tiles'):
            build_3dtiles(args, tree, reconstruction, self.rerun())

        if args.copy_to:
            try:
                copy_paths([os.path.join(args.project_path, p) for p in get_processing_results_paths()], args.copy_to, self.rerun())
            except Exception as e:
                log.WARNING("Cannot copy to %s: %s" % (args.copy_to, str(e)))

