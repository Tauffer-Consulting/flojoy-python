from box import Box
import numpy as np
import traceback
import yaml
import json
import re
from pathlib import Path
from collections import UserDict

from redis import Redis
from rq.job import Job

class CtrlPanel():
    '''
    A class for the flojoy dashboard UI

    Usage
    -----
    panel = CtrlPanel()

    print(panel.get_state()['SINE'])

    {
        frequency: ...,
        amplitude: ...,
        ...
    }
    '''

    def get_state(self):
        root = get_flojoy_root_dir()
        path = root + 'PYTHON/WATCH/fc.json'
        f = open(path)
        fc = json.loads(f.read())
        elems = fc['elements']
        
        ctrls_dict = dict()

        for i in range(len(elems)):
            el = elems[i]
            if 'source' not in el:
                data = el['data']
                ctrls = data['ctrls'] if 'ctrls' in data else {}
                label = el['id'].split('-')[0]
                ctrls_dict[label] = ctrls

        return ctrls_dict

class VectorXY(Box):
    '''
    A class for x-y paired numpy arrays that supports dot assignment

    Usage
    -----
    import numpy as np

    v = VectorXY()

    v.x = np.linspace(1,20,0.1)
    v.y = np.sin(v.x)
    '''

    @staticmethod
    def _ndarrayify(value):
        s = str(type(value))
        v_type = s.split("'")[1]

        match v_type:
            case 'int' | 'float':
                value = np.array([value])
            case 'list':
                value = np.array(value)
            case 'numpy.ndarray':
                pass
            case _:
                raise ValueError(value)
        return value
    
    def __init__(self, **kwargs):
        if 'x' in kwargs:
            self['x'] = self._ndarrayify(kwargs['x'])
        else:
            self['x'] = np.array([])
        
        if 'y' in kwargs:
            self['y'] = self._ndarrayify(kwargs['y'])
        else:
            self['y'] = np.array([])

    def __getitem__(self, key, **kwargs):
        if key not in ['x','y']:
            raise KeyError(key)
        elif key == '_ignore_default':
            pass
        else:
            return super().__getitem__(key)

    def __setitem__(self, key, value):
        if key not in ['x','y']:
            raise KeyError(key)
        else:
            value = self._ndarrayify(value)
            super().__setitem__(key, value)

def get_flojoy_root_dir():
    home = str(Path.home())
    path = home + '/.flojoy/flojoy.yaml' # TODO: Upate shell script to add ~/.flojoy/flojoy.yaml
    stream = open(path, 'r')
    yaml_dict = yaml.load(stream, Loader=yaml.FullLoader)
    return yaml_dict['PATH']

def js_to_json(s):
    '''
    Converts an ES6 JS file with a single JS Object definition to JSON
    '''
    split = s.split('=')[1]
    clean = split.replace('\n','').replace("'",'').replace(',}','}').rstrip(';')
    single_space = ''.join(clean.split())
    dbl_quotes = re.sub(r'(\w+)',r'"\1"', single_space).replace('""', '"')
    rm_comma = dbl_quotes.replace('},}', '}}')

    return json.loads(rm_comma)

def get_parameter_manifest():
    root = get_flojoy_root_dir()
    f = open(root + 'src/components/flow_chart_panel/PARAMETERS_MANIFEST.js')
    param_manifest = js_to_json(f.read())
    return param_manifest

def fetch_inputs(previous_job_ids, mock=False):
    '''
    Queries Redis for job results

    Parameters
    ----------
    previous_job_ids : list of Redis job IDs that directly precede this node
    
    Returns
    -------
    inputs : list of VectorXY objects
    '''
    if mock is True:
        return [VectorXY(x = np.linspace(0,10,100))]

    inputs = []

    try:
        for ea in previous_job_ids:
            job = Job.fetch(ea, connection=Redis())
            inputs.append(job.result)
    except Exception:
        print(traceback.format_exc())

    return inputs

def flojoy(func):
    '''
    Decorator to turn Python functions with numerical return
    values into Flojoy nodes.

    @flojoy is intended to eliminate  boilerplate in connecting
    Python scripts as visual nodes 

    Into whatever function it wraps, @flojoy injects
    1. the last node's input as an XYVector
    2. parameters for that function (either set byt the user or default)

    Parameters
    ----------
    func : Python function object

    Returns
    -------
    VectorYX object 

    Usage Example
    -------------

    @flojoy
    def SINE(v, params):

        print('params passed to SINE', params)

        output = VectorXY(
            x=v[0].x, 
            y=np.sin(v[0].x)
        )
        return output

    pj_ids = [123, 456]

    # equivalent to: decorated_sin = flojoy(SINE)
    print(SINE(previous_job_ids = pj_ids, mock = True))    
    '''

    def inner(previous_job_ids, mock):
        FN = func.__name__

        # Get default command paramaters
        default_params = {}
        pm = get_parameter_manifest()
        for param in pm[FN]:
            default_params[param] = pm[FN][param]['default']

        # Get command parameters set by the user through the control panel
        panel = CtrlPanel()
        user_set_parameters = panel.get_state()
        func_params = user_set_parameters[FN] if FN in user_set_parameters else default_params

        # Make sure that function parameters set is fully loaded
        # If function is missing a parameter, fill-in with default value
        for key in default_params.keys():
            if key not in func_params.keys():
                func_params[key] = default_params[key]

        node_inputs = fetch_inputs(previous_job_ids, mock)

        print('Executing function ', FN, ' where  pjs = ', previous_job_ids)

        return func(node_inputs, func_params)
    
    return inner

