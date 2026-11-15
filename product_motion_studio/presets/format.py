"""FORMAT presets: DATA dicts with the output resolution.

SCHEMA   register('format', id, name, category, desc, data=dict(res=(width, height)))
RULES    - id is the ratio label ('16:9', '9:16'...). Standard delivery resolutions, even numbers.
         - The camera fit reads the aspect from the scene, so every format re-frames by itself.
"""

from . import register

for _id, _name, _res, _cat in (('16:9', '16:9 Landscape', (1920, 1080), 'video'),
                               ('9:16', '9:16 Vertical', (1080, 1920), 'social'),
                               ('1:1', '1:1 Square', (1080, 1080), 'social'),
                               ('4:5', '4:5 Portrait', (1080, 1350), 'social'),
                               ('21:9', '21:9 Ultrawide', (2560, 1080), 'video'),
                               ('4:3', '4:3 Classic', (1440, 1080), 'video'),
                               ('2.39:1', '2.39:1 Cinemascope', (2048, 858), 'video'),
                               ('2:3', '2:3 Pinterest Pin', (1000, 1500), 'social'),
                               ('3:4', '3:4 Print Catalogue', (3600, 4800), 'print'),
                               ('1.9:1', '1.9:1 DCI 4K Cinema', (4096, 2160), 'video'),
                               ('2.44:1', '2.44:1 Amazon A+ Banner', (1464, 600), 'web'),
                               ('16:9_720', '16:9 Web Hero 720p', (1280, 720), 'web')):
    register('format', _id, _name, _cat, f'{_res[0]}x{_res[1]}', data=dict(res=_res))
