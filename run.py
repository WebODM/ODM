#!/usr/bin/python3

# Basic check
import sys
if sys.version_info.major < 3:
    print("Ups! ODM needs to run with Python 3. It seems you launched it with Python 2. Try using: python3 run.py ... ")
    sys.exit(1)

import os
from opendm import log
from opendm import config
from opendm import system
from opendm import io
from opendm.progress import progressbc
from opendm.utils import get_processing_results_paths, rm_r
from opendm.arghelpers import args_to_dict, save_opts, find_rerun_stage

from stages.odm_app import ODMApp

def odm_version():
    try:
        with open("VERSION") as f:
            return f.read().split("\n")[0].strip()
    except:
        return "?"

if __name__ == '__main__':
    args = config.config()

    log.ODM_INFO('Initializing ODM %s - %s' % (odm_version(), system.now()))

    progressbc.set_project_name(args.name)
    args.project_path = os.path.join(args.project_path, args.name)

    if not io.dir_exists(args.project_path):
        log.ODM_ERROR('Directory %s does not exist.' % args.name)
        exit(1)

    opts_json = os.path.join(args.project_path, "options.json")
    auto_rerun_stage, opts_diff = find_rerun_stage(opts_json, args, config.rerun_stages, config.processopts)
    if auto_rerun_stage is not None and len(auto_rerun_stage) > 0:
        log.ODM_INFO("Rerunning from: %s" % auto_rerun_stage[0])
        args.rerun_from = auto_rerun_stage

    # Print args
    args_dict = args_to_dict(args)
    log.ODM_INFO('==============')
    for k in args_dict.keys():
        log.ODM_INFO('%s: %s%s' % (k, args_dict[k], ' [changed]' if k in opts_diff else ''))
    log.ODM_INFO('==============')
    

    # If user asks to rerun everything, delete all of the existing progress directories.
    if args.rerun_all:
        log.ODM_INFO("Rerun all -- Removing old data")
        for d in [os.path.join(args.project_path, p) for p in get_processing_results_paths()] + [
                  os.path.join(args.project_path, "odm_meshing"),
                  os.path.join(args.project_path, "opensfm"),
                  os.path.join(args.project_path, "odm_texturing_25d"),
                  os.path.join(args.project_path, "odm_filterpoints"),
                  os.path.join(args.project_path, "submodels")]:
            rm_r(d)

    app = ODMApp(args)
    retcode = app.execute()

    if retcode == 0:
        save_opts(opts_json, args)
    
    # Do not show end message for local submodels runs
    if retcode == 0 and not "submodels" in args.project_path:
        log.ODM_INFO('Done! d-(^_^)z')
        log.ODM_INFO('ODM app finished - %s' % system.now())
    else:
        exit(retcode)