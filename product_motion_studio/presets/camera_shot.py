"""CAMERA SHOT presets: static framings, DATA dicts.

SCHEMA   register('camera_shot', id, name, category, desc, data=dict(
             az=deg (0 = in front, +az moves the camera to +X),  el=deg above the target (may be < 0),
             lens=mm (tele 85-150 for products),  padding=fraction of the half frame left empty
             (0.2 = product fills 80% of the limiting side; NEGATIVE = deliberate crop, keep >= -0.15),
             dof=f-stop (0 = DOF off),  target_z=0..1 height of the look-at point on the product (default 0.5)))
RULES    - Never put distances in data: the builder FITS the camera distance to the product bbox,
           lens, aspect ratio and padding (scale-independent, works for every format).
         - Lights and backdrop follow `az`, so keep az/el semantics unchanged.
         - The camera is never allowed below the floor: the builder raises `el` if needed.
"""

from . import register

register('camera_shot', 'hero_34', 'Hero 3/4', 'hero', 'Classic three-quarter hero view, slightly above.',
         data=dict(az=35, el=18, lens=85, padding=0.2, dof=5.6))
register('camera_shot', 'front', 'Front', 'hero', 'Straight-on, symmetric pack shot.',
         data=dict(az=0, el=4, lens=85, padding=0.2, dof=8.0))
register('camera_shot', 'low_angle', 'Low Angle', 'hero', 'Camera near the floor looking up: power and presence.',
         data=dict(az=20, el=-4, lens=85, padding=0.2, dof=5.6, target_z=0.55))
register('camera_shot', 'top_down', 'Top Down', 'flat', 'Flat-lay view from above.',
         data=dict(az=0, el=88, lens=100, padding=0.2, dof=8.0))
register('camera_shot', 'macro', 'Macro', 'detail', 'Tight tele close-up with shallow depth of field (product slightly cropped).',
         data=dict(az=30, el=10, lens=150, padding=-0.12, dof=2.8))
register('camera_shot', 'side', 'Side', 'hero', 'Pure profile view.',
         data=dict(az=90, el=6, lens=85, padding=0.2, dof=8.0))
register('camera_shot', 'high_34', 'High 3/4', 'hero', 'Three-quarter view from well above: shows the top and the front together.',
         data=dict(az=35, el=38, lens=85, padding=0.2, dof=5.6, target_z=0.45))
register('camera_shot', 'rear_34', 'Rear 3/4', 'hero', 'Three-quarter view from behind: back detail, ports, branding on the rear.',
         data=dict(az=145, el=18, lens=85, padding=0.2, dof=5.6))
register('camera_shot', 'profile_tight', 'Profile Tight', 'detail', 'Tight tele profile, product slightly larger than the frame: silhouette and thickness.',
         data=dict(az=90, el=4, lens=135, padding=0.0, dof=4.0))
register('camera_shot', 'worms_eye', "Worm's Eye", 'hero', 'As low as the floor allows, looking up: monumental, heroic product.',
         data=dict(az=15, el=-14, lens=60, padding=0.15, dof=5.6, target_z=0.6))
register('camera_shot', 'macro_side', 'Macro Detail Side', 'detail', 'Extreme tele close-up from the side with razor-thin focus: texture and material.',
         data=dict(az=75, el=8, lens=200, padding=-0.15, dof=2.8))
register('camera_shot', 'wide_establishing', 'Wide Establishing', 'wide', 'Product small in a large empty space: room for titles and the backdrop.',
         data=dict(az=25, el=14, lens=50, padding=0.5, dof=8.0))
