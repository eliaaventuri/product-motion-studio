"""Quality tests of the 25 camera_motion presets (speed, smoothness, framing, lens/focus, handheld, combinations):
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_camera_quality.py
Measures every preset x shot (hero_34, front, low_angle, macro) x duration (48, 96, 200, 480 frames @ 24 fps) with
plugin/tools/camera_report.py (see its docstring for the metrics).  Only Workbench, never Cycles/Eevee.
Each test lists its violations (first few): the final line counts them all.  Thresholds live here, at the top.
The family rules and exceptions are documented at the top of presets/camera_motion.py."""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))

import numpy as np
import bpy

import camera_report as cr
from product_motion_studio import api, core, presets

# ---- thresholds -------------------------------------------------------------------------------------------------
OMEGA_MAX = 32.0                 # deg/s, peak angular speed of any non-whip move at any duration (~30 + margin)
OMEGA_MIN = {'orbit': 5.5, 'crane': 5.0}          # deg/s at 200/480 frames: the move must stay perceptible
WHIP_OMEGA_MAX = 180.0           # deg/s, the declared whip
REL_MAX = {'dolly': 0.12, 'dolly_slow': 0.05, 'dolly_fast': 0.40, 'dolly_reveal': 0.25}   # peak (d dist/dt)/dist per second
REL_MIN = {'dolly': 0.004, 'dolly_slow': 0.003, 'dolly_fast': 0.004, 'dolly_reveal': 0.004}   # 1/s at 200/480 frames (macro shots included)
SLIDE_SPEED_MAX = 1.0            # size/s
EASE_MAX = 0.08                  # speed at the first/last frame over the peak: 0 = starts and stops from rest
JERK_MAX = 12.0                  # smoothness index (see camera_report): quintic ~3.4, cubic ease with jump ~50
OVER_MAX = 0.20                  # product outside the frame, fraction of its extent (test 5 of test_addon)
OVER_MAX_UNCROPPED = 0.10        # same on shots that do not crop the product on purpose
CENTER_DEV_MAX = 0.30            # the product centre stays within +-30 % of the frame centre
LENS_STILL = 0.01                # mm: lens change allowed outside dolly_zoom
FOCUS_STILL = 1e-6               # size: focus-empty change allowed outside rack_focus
DOLLY_ZOOM_MIN_MM = 8.0          # mm of lens change at 96+ frames
DOLLY_ZOOM_FILL = 1.30           # max/min size of the product in frame during a dolly zoom
RACK_SHIFT_MIN = 0.6             # size, focus travel of rack_focus
RACK_BLUR_MIN = 0.8              # % of the sensor width: defocus of the unfocused side, both at the start and at the end
HAND_PP_MIN, HAND_PP_MAX = 0.25, 1.0       # deg peak-to-peak of the camera rotation noise
HAND_HIGH_MAX = 0.12             # share of the noise energy above 6 Hz (digital jitter)
HAND_LOW_MIN, HAND_MID_MIN = 0.35, 0.04    # shares below 2 Hz and in 2-6 Hz (mixed frequencies)
LOOP_RATE_VAR = 0.03             # constant-speed loop: azimuth rate variation
SIGNATURE_MIN = 0.012            # presets must differ: min RMS distance between normalised az/el/dist/lens curves
PAIR_YAW_MIN = {'spin_360_loop+orbit_360_loop': 180.0, 'luxury_drift+arc_push': 30.0}   # deg of apparent product yaw

FAMILY = dict(static='hold', push_in='dolly', pull_back='dolly', orbit_90='orbit', orbit_360_loop='loop',
              crane_up='crane', push_in_slow='dolly_slow', push_in_fast='dolly_fast', pull_back_reveal='dolly_reveal',
              orbit_45_left='orbit', orbit_45_right='orbit', orbit_90_left='orbit', orbit_180_right='orbit',
              orbit_rise='orbit', top_down_spiral='orbit', pendulum='orbit', arc_push='orbit',
              whip_orbit_finale='whip', crane_down='crane', low_angle_hero_rise='crane', pedestal_rise='slide',
              truck_right='slide', truck_left='slide',
              dolly_zoom='lens', rack_focus='rack', handheld='handheld',
              telephoto_snap_zoom='lens', micro_breathing_macro='handheld',
              helical_push_orbit='orbit', crane_to_zenith_90='crane')
CROPPED_SHOTS = ('macro', 'macro_side', 'profile_tight')       # shots that crop the product on purpose (padding < 0.05)
PAIRS = [('spin_360_loop', 'orbit_360_loop'), ('drop_impact', 'push_in'), ('luxury_drift', 'arc_push'),
         ('flip', 'crane_up'), ('pop_in_reveal', 'pull_back_reveal'), ('fly_by_swoop', 'static')]

RESULTS = []
DATA = {}


def test(num, name):
    def deco(fn):
        try:
            bad, info = fn()
            msg = info + (f"  | {len(bad)} violations: " + "; ".join(bad[:4]) if bad else '')
            RESULTS.append((num, name, not bad, msg, len(bad)))
        except Exception as e:                      # noqa: BLE001
            traceback.print_exc()
            RESULTS.append((num, name, False, f"{type(e).__name__}: {e}", 1))
        return fn
    return deco


def cases():
    for key, v in DATA.items():
        pid, shot, dur = key.split('|')
        yield pid, shot, int(dur), v


def check_registry():
    ids = list(presets.REGISTRY['camera_motion'])
    assert set(ids) == set(FAMILY), (set(ids) ^ set(FAMILY))
    return ids


cr.setup()
IDS = check_registry()
SHOTS = list(presets.REGISTRY['camera_shot']) if '--all-shots' in sys.argv else list(cr.SHOTS)   # all 12 shots: slow
DATA, _ = cr.run_cases(IDS, SHOTS, cr.DURS)


@test(1, "smooth: ease in/out from rest, no stop-and-go, low jerk (loops, static and handheld exempt)")
def t1():
    bad, worst = [], 0.0
    for pid, shot, dur, v in cases():
        if FAMILY[pid] in ('hold', 'loop', 'handheld'):
            continue
        stop_ok = pid == 'pendulum'                     # a pendulum stops at each apex (declared)
        worst = max(worst, v['jerk_index'])
        for what, ok in (('ease_in', v['ease_in'] <= EASE_MAX), ('ease_out', v['ease_out'] <= EASE_MAX),
                         ('stop_go', stop_ok or not v['stop_go']), ('jerk', v['jerk_index'] <= JERK_MAX)):
            if not ok:
                bad.append(f"{pid}/{shot}/{dur} {what} (in {v['ease_in']:.2f} out {v['ease_out']:.2f} J {v['jerk_index']:.0f})")
    return bad, f"worst jerk index {worst:.1f}"


@test(2, "credible speeds: orbits/cranes <= 30 deg/s at every duration, >= 5 deg/s on long clips; dollies in %/s")
def t2():
    bad = []
    for pid, shot, dur, v in cases():
        fam = FAMILY[pid]
        ang = max(v['peak_omega'], v['peak_az'], v['peak_el'])      # (near the zenith the azimuth turns the picture)
        if fam in ('orbit', 'crane', 'lens'):
            if ang > OMEGA_MAX:
                bad.append(f"{pid}/{shot}/{dur} omega {ang:.0f}")
            if fam in OMEGA_MIN and dur >= 200 and ang < OMEGA_MIN[fam]:
                bad.append(f"{pid}/{shot}/{dur} too slow {ang:.1f}")
        elif fam == 'whip':
            if ang > WHIP_OMEGA_MAX:
                bad.append(f"{pid}/{shot}/{dur} whip omega {ang:.0f}")
        elif fam in REL_MAX:
            if v['peak_rel'] > REL_MAX[fam]:
                bad.append(f"{pid}/{shot}/{dur} rate {v['peak_rel']:.3f}/s")
            if dur >= 200 and v['peak_rel'] < REL_MIN[fam]:
                bad.append(f"{pid}/{shot}/{dur} imperceptible {v['peak_rel']:.4f}/s")
        elif fam == 'slide' and v['peak_speed'] > SLIDE_SPEED_MAX:
            bad.append(f"{pid}/{shot}/{dur} speed {v['peak_speed']:.2f}")
    return bad, f"{sum(1 for _ in cases())} cases"


@test(3, "composition: product always in frame (overflow <= 20 %, <= 10 % on uncropped shots), centre inside")
def t3():
    bad, worst = [], 0.0
    for pid, shot, dur, v in cases():
        lim = OVER_MAX if shot in CROPPED_SHOTS else OVER_MAX_UNCROPPED
        worst = max(worst, v['max_over'])
        if v['max_over'] > lim or v['center_out'] or v['cx_dev'] > CENTER_DEV_MAX or v['cy_dev'] > CENTER_DEV_MAX:
            bad.append(f"{pid}/{shot}/{dur} over {v['max_over']:.2f} out {v['center_out']} dev {v['cx_dev']:.2f},{v['cy_dev']:.2f}")
    return bad, f"worst overflow {worst:.1%}"


@test(4, "lens and focus change only in dolly_zoom / rack_focus / telephoto_snap_zoom; both are really visible")
def t4():
    bad = []
    for pid, shot, dur, v in cases():
        if pid not in ('dolly_zoom', 'telephoto_snap_zoom') and v['lens_range'] > LENS_STILL:
            bad.append(f"{pid}/{shot}/{dur} lens moves {v['lens_range']:.2f} mm")
        if pid != 'rack_focus' and v['focus_shift'] > FOCUS_STILL:
            bad.append(f"{pid}/{shot}/{dur} focus moves {v['focus_shift']:.3f}")
        if pid == 'dolly_zoom' and dur >= 96:
            if v['lens_range'] < DOLLY_ZOOM_MIN_MM or v['fill_max'] / v['fill_min'] > DOLLY_ZOOM_FILL:
                bad.append(f"{pid}/{shot}/{dur} lens {v['lens_range']:.1f} mm, size x{v['fill_max'] / v['fill_min']:.2f}")
        if pid == 'rack_focus' and dur >= 96:
            if v['focus_shift'] < RACK_SHIFT_MIN or v['rack_a'] < RACK_BLUR_MIN or v['rack_b'] > -RACK_BLUR_MIN:
                bad.append(f"{pid}/{shot}/{dur} focus {v['focus_shift']:.2f} blur {v['rack_a']:.2f}%/{v['rack_b']:.2f}%")
        if pid == 'telephoto_snap_zoom' and dur >= 96:
            if v['lens_range'] < DOLLY_ZOOM_MIN_MM:
                bad.append(f"{pid}/{shot}/{dur} lens {v['lens_range']:.1f} mm")
            # telephoto_snap_zoom intentionally changes the product size (ratio ~1.8), wider fill range allowed
            if v['fill_max'] / v['fill_min'] > 2.5:
                bad.append(f"{pid}/{shot}/{dur} size x{v['fill_max'] / v['fill_min']:.2f}")
    rk = [v for p, s, d, v in cases() if p == 'rack_focus' and s == 'hero_34' and d == 200][0]
    return bad, f"rack hero_34/200: f/{rk['fstop']:.2f}, defocus {rk['rack_a']:.1f}% -> {rk['rack_b']:.1f}% of the sensor"


@test(5, "handheld: small mixed-frequency noise, no digital jitter, product stays in frame")
def t5():
    bad = []
    for pid, shot, dur, v in cases():
        if pid != 'handheld' or dur < 96:
            continue
        nb = v['noise_bands']
        if not (HAND_PP_MIN <= v['noise_deg'] <= HAND_PP_MAX):
            bad.append(f"{shot}/{dur} amplitude {v['noise_deg']:.2f} deg p-p")
        if nb[3] > HAND_HIGH_MAX or nb[0] + nb[1] < HAND_LOW_MIN or nb[2] < HAND_MID_MIN:
            bad.append(f"{shot}/{dur} spectrum {[round(x, 2) for x in nb]}")
    v = [v for p, s, d, v in cases() if p == 'handheld' and s == 'hero_34' and d == 200][0]
    return bad, f"hero_34/200: {v['noise_deg']:.2f} deg p-p, bands {[round(x, 2) for x in v['noise_bands']]}"


@test(6, "holds and the whip: reveal holds first, whip holds at the end, loop turns 360 at constant speed")
def t6():
    bad = []
    for pid, shot, dur, v in cases():
        if pid == 'pull_back_reveal' and dur >= 96 and v['hold_in'] < 0.3:
            bad.append(f"{pid}/{shot}/{dur} hold_in {v['hold_in']:.2f}s")
        if pid == 'whip_orbit_finale' and v['hold_out'] < 0.2:
            bad.append(f"{pid}/{shot}/{dur} hold_out {v['hold_out']:.2f}s")
        if pid == 'orbit_360_loop' and abs(abs(v['az_total']) - 360) > 0.5:
            bad.append(f"{pid}/{shot}/{dur} azimuth {v['az_total']:.1f}")
    _, series = cr.run_cases(['orbit_360_loop'], ['hero_34'], [200], keep_series=True)
    s = next(iter(series.values()))
    rate = np.diff(s['az'])
    if (rate.max() - rate.min()) / abs(rate.mean()) > LOOP_RATE_VAR:
        bad.append(f"orbit_360_loop azimuth rate varies {(rate.max() - rate.min()) / abs(rate.mean()):.3f}")
    if abs(s['az'][-1] - s['az'][0]) < 6.2 or abs(s['el'][-1] - s['el'][0]) > 1e-6:
        bad.append("orbit_360_loop does not close")
    return bad, "ok"


@test(7, "the 6 typical combinations with a product motion stay framed; spin+orbit and luxury+arc do not cancel")
def t7():
    bad, info = [], []
    for pm, cm in PAIRS:
        for shot in ('hero_34', 'front'):
            base = {}
            for cam_id in ('static', cm):                 # same product motion with a locked camera: what is out of frame anyway
                cr.setup(product_motion=pm, camera_motion=cam_id, shot=shot, duration=200)
                sc = bpy.context.scene
                f0, f1 = core.frame_range(core.settings(sc))
                s, inf, cam = cr.sample(sc, f0, f1)
                base[cam_id] = s
            s, ref = base[cm], base['static']
            worse = float((s['over'] - ref['over']).max())      # camera made the product leave the frame more
            lost = int(s['out'].sum() - ref['out'].sum())
            if worse > 0.08 or lost > 0:
                bad.append(f"{pm}+{cm}/{shot} worse by {worse:.2f}, centre out +{lost}")
            rel = np.degrees(np.unwrap(s['prod_yaw']) - np.unwrap(s['az']))
            need = PAIR_YAW_MIN.get(f"{pm}+{cm}")
            if shot == 'hero_34':
                tpk = (int(np.argmax(np.linalg.norm(np.gradient(s['pos'], axis=0), axis=1))) / max(1, f1 - f0))
                info.append(f"{pm}+{cm}: worse {worse:+.2f}, apparent yaw {rel[-1] - rel[0]:+.0f}, cam peak at {tpk:.0%}")
                if need and abs(rel[-1] - rel[0]) < need:
                    bad.append(f"{pm}+{cm} cancel: apparent yaw {rel[-1] - rel[0]:+.0f} deg < {need}")
    return bad, " | ".join(info)


@test(8, "presets are distinct from each other (normalised az/el/distance/lens curves, hero_34, 200 frames)")
def t8():
    cr.setup()
    sc = bpy.context.scene
    sig = {}
    for pid in IDS:
        api.apply('camera_motion', pid, duration=200)
        f0, f1 = core.frame_range(core.settings(sc))
        s, inf, cam = cr.sample(sc, f0, f1)
        d0 = s['dist'][0]
        sig[pid] = np.concatenate([np.degrees(s['az'] - s['az'][0]) / 90, np.degrees(s['el'] - s['el'][0]) / 30,
                                   (s['dist'] / d0 - 1) / 0.3, (s['lens'] / s['lens'][0] - 1) / 0.3,
                                   np.linalg.norm(s['focus'] - s['focus'][0], axis=1) / inf.size,
                                   ((s['pos'] - s['pos'][0]) / inf.size).ravel(),
                                   np.degrees(s['rot'] - s['rot'][0]).ravel()])
    bad, close = [], 9.0
    for i, a in enumerate(IDS):
        for b in IDS[i + 1:]:
            dist = float(np.sqrt(np.mean((sig[a] - sig[b]) ** 2)))
            close = min(close, dist) if a != 'static' and b != 'static' else close
            if dist < SIGNATURE_MIN and 'static' not in (a, b):
                bad.append(f"{a} ~ {b} ({dist:.3f})")
    return bad, f"closest pair distance {close:.3f}"


print("\n==== PMS CAMERA QUALITY RESULTS ====")
for num, name, ok, msg, n in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {num}. {name}  {msg}")
fails = [r for r in RESULTS if not r[2]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed, {sum(r[4] for r in RESULTS if not r[2])} violations ====")
sys.exit(1 if fails else 0)
