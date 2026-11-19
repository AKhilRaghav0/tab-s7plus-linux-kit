# UDFPS (optical in-display fingerprint) on Droidian – Galaxy Tab S7+ (SM-T970 / gts7xlwifi)

Research date: 2026-11-19. This came from reading source only. Nothing was run on the device.
Repos were cloned at their current HEADs: LineageOS `android_hardware_samsung` lineage-24.0 (commit 626867f), `android_device_samsung_gts7xlwifi` lineage-24.0, `android_device_samsung_sm8250-common` lineage-24.0, and `mukahraman/kernel_samsung_sm8250` branch `droidian`.

---

## TL;DR

* **The missing piece is one call:** `sehRequest(22 /*SEM_REQUEST_TOUCH_EVENT*/, 2 /*pressed*/)` when the finger lands on the sensor, then `sehRequest(22, 1 /*released*/)` when it lifts. LineageOS does this on gts7xlwifi (`ro.vendor.fingerprint.request_touch_event=true`). TrebleDroid/phh GSIs do the same against the stock Samsung vendor HAL. droidian-fpd only talks to the AOSP `@2.1` interface, so the Samsung TA never starts a capture and enrollment times out. That matches what you saw: `ACQUIRED_VENDOR`, then `ERROR_TIMEOUT` after 60 s.
* **Binder call (stock Android 11 vendor):** hwbinder service `vendor.samsung.hardware.biometrics.fingerprint@3.0::ISehBiometricsFingerprint/default`, interface token `vendor.samsung.hardware.biometrics.fingerprint@3.0::ISehBiometricsFingerprint`, **transaction code 11**. Arguments: `int32 cmdId, int32 inParam, vec<int8_t> inBuf` (empty is fine). The reply carries `int32 retval, vec<int8_t> outBuf`.
* **TSP:** `fod_enable,1,1,0` goes to `/sys/class/sec/tsp/cmd`. LineageOS writes it at `on init`. Optionally also send `set_fod_rect,l,t,r,b`. With FOD enabled, the TSP firmware reports FOD press/release/out only through `sysfs_notify()` on `/sys/class/sec/tsp/scrub_pos`. It sends **no input key code**. The simplest trigger is still the normal multitouch coordinates from `sec_touchscreen` landing inside the sensor circle.
* **Sensor location (LineageOS):** `ro.vendor.fingerprint.sensor_location=876|2614|77`. That is x|y|radius in native portrait panel pixels (1752×2800). The TSP's `stm,max_coords = <1751 2799>`, so raw evdev coordinates are in the same space.
* **Display:** in both the LineageOS and Droidian kernels, the panel driver (ANA38401) has the Samsung optical-FP mask/HBM path **disabled** (`//samsung,support-optical-fingerprint;`). Nothing in the kernel lights the sensor area. Userspace has to draw a bright white disc there (and raise the backlight) before sending the touch event. LineageOS's 100 ms "wait for mask brightness" therefore just times out on this device.
* **Prior art:** I found nobody who has UDFPS working on Droidian, Ubuntu Touch or postmarketOS for any Samsung device. Details are in section 4.

---

## 1. How LineageOS implements UDFPS for gts7xlwifi / SM8250 Samsung

### 1.1 Device configuration

`LineageOS/android_device_samsung_gts7xlwifi` (lineage-24.0):

* `vendor.prop` lines 9-14:
  ```
  # Fingerprint
  ro.vendor.fingerprint.type=udfps_optical
  ro.vendor.fingerprint.screen_off_press_delay=600
  ro.vendor.fingerprint.sensor_location=876|2614|77
  ro.vendor.fingerprint.request_touch_event=true
  ro.vendor.fingerprint.mask_brightness_path=/sys/class/lcd/panel/actual_mask_brightness
  ```
* `BoardConfig.mk` ~L31-33: `TARGET_ADDITIONAL_GRALLOC_10_USAGE_BITS := 0x2000U | 0x400000000LL`, `TARGET_USES_FOD_ZPOS := true`.
* `device.mk` L57-59: `soong_config_set,samsungUdfpsVars,udfps_zorder,0x20000000u` and the surfaceflinger `udfps_lib` = `//hardware/samsung/fingerprint:libudfps_extension.samsung`. These are SurfaceFlinger z-order and usage-bit hooks used only by the Android compositor. They are irrelevant on Phosh.
* `overlay/frameworks/base/packages/SystemUI/res/values/dimens.xml`: `physical_fingerprint_sensor_center_screen_location_y = 2614px`.
* `init/init.gts7xlwifi.rc` (post-fs): `chmod 0660 /dev/goodix_fp`, `chown system system /dev/goodix_fp`, plus chowns on `/sys/class/fingerprint/fingerprint/*`.

`LineageOS/android_device_samsung_sm8250-common` (lineage-24.0):

* `init/init.fingerprint.rc` L5-6:
  ```
  on init
      write /sys/class/sec/tsp/cmd "fod_enable,1,1,0"
  ```
* `init/init.samsung.rc` ~L84-90 (early-boot): `chown system system /sys/class/sec/tsp/cmd`, `.../tsp/input/fod_pressed`. The fts1ba90a driver used on gts7xl does not create `fod_pressed`; see section 2.
* `init/init.samsung.display.rc` ~L428-440: "FINGERPRINT MASK" chowns for `/sys/class/lcd/panel/mask_brightness` and `actual_mask_brightness`.
* `common.mk` L177-179: the HAL is `android.hardware.biometrics.fingerprint-service.samsung`, the AIDL HAL from `hardware/samsung`.

### 1.2 The HAL wrapper: `LineageOS/android_hardware_samsung/aidl/fingerprint/`

**LineageOS does not use Samsung's `vendor.samsung.hardware.biometrics.fingerprint@3.0-service`.** It replaces it with its own AIDL service, which `dlopen()`s Samsung's library directly. `LegacyHAL.cpp` L19-24:

```cpp
void* handle = dlopen("libbauthserver.so", RTLD_NOW);
if (!handle) handle = dlopen("libsfp_sensor.so", RTLD_NOW);
... dlsym(handle, "ss_fingerprint_request") ...
int LegacyHAL::request(int cmd, int param) {
    int result = ss_fingerprint_request(cmd, nullptr, 0, nullptr, 0, param);
```

The `ss_fingerprint_request` signature (`LegacyHAL.h` L35):
`int (*ss_fingerprint_request)(uint32_t cmd, char* inBuf, uint32_t inBuf_length, char* outBuf, uint32_t outBuf_length, uint32_t param);`

The stock vendor `@3.0-service` wraps the same `libbauthserver.so`. Its `sehRequest(cmdId, inParam, inBuf)` ends up calling `ss_fingerprint_request(cmdId, …, inParam)`. The gustavo-hc reimplementation in section 1.4 confirms this mapping.

**Command IDs** (`VendorConstants.h`, the relevant ones):

```c
#define FINGERPRINT_REQUEST_GET_SENSOR_INFO 5
#define FINGERPRINT_REQUEST_GET_SENSOR_STATUS 6
#define SEM_REQUEST_FORCE_CBGE 21
#define SEM_REQUEST_TOUCH_EVENT 22                 // <-- the one that matters
#define SEM_REQUEST_SHOW_INDISPLAY_AUTH_ANIMATION 1009
#define SEM_REQUEST_SET_SCREEN_STATUS 0x3F0
#define SEM_REQUEST_MASK_CTL 0x3F5
#define SEM_REQUEST_OPTICAL_CALIBRATION 0x3F8
#define SEM_REQUEST_GET_TSP_BLOCK_STATUS 0x3F9
// events delivered as acquired_info (> 10000) via notify():
#define SEM_FINGERPRINT_EVENT_CAPTURE_READY 10001
#define SEM_FINGERPRINT_EVENT_CAPTURE_STARTED 10002
#define SEM_FINGERPRINT_EVENT_CAPTURE_COMPLETED 10003
#define SEM_FINGERPRINT_EVENT_FINGER_LEAVE 10004
#define SEM_FINGERPRINT_ACQUIRED_TSP_BLOCK 1004 / TSP_UNBLOCK 1005, LIGHT_TOUCH 1003, WET_FINGER 1001
```

**Finger down/up handling** (`Session.cpp` L242-264):

```cpp
ndk::ScopedAStatus Session::onPointerDown(...) {
    if (FingerprintHalProperties::request_touch_event().value_or(false)) {
        waitForMaskBrightness();                       // poll actual_mask_brightness, 100 ms timeout
        mHal.request(SEM_REQUEST_TOUCH_EVENT, 2);      // 22, 2 = finger pressed
    }
    checkSensorLockout();
    mCb->onAcquired(AcquiredInfo::START, 0);
}
ndk::ScopedAStatus Session::onPointerUp(...) {
    if (FingerprintHalProperties::request_touch_event().value_or(false))
        mHal.request(SEM_REQUEST_TOUCH_EVENT, 1);      // 22, 1 = finger released
}
```

`waitForMaskBrightness()` (`Session.cpp` L34-69) opens `ro.vendor.fingerprint.mask_brightness_path` and polls it for `POLLPRI|POLLERR` for up to `kMaskBrightnessTimeoutMs = 100`. A code comment explains why: "The sensor captures as soon as it gets the touch event, so wait for the panel to report finger mask brightness, otherwise the first image is too dark."

`onPointerDownWithContext()` adds an extra `screen_off_press_delay` sleep (600 ms on gts7xlwifi) only when the screen is off (AOD/NO_UI).

`enroll()` (`Session.cpp` ~L108-135) calls `ss_fingerprint_enroll(&hat, userId, 0 /*timeoutSec*/)`. It sends `SEM_REQUEST_FORCE_CBGE` only if `ro.vendor.fingerprint.force_calibrate` is set, and it is **not** set for gts7xlwifi. `Fingerprint::notify()` (`Fingerprint.cpp` L161-175) diverts acquired codes above 10000 to `handleEvent()`.

**Sensor location** (`Fingerprint.cpp` L115-135) is parsed from `ro.vendor.fingerprint.sensor_location` as `x|y|radius[|display]` → `SensorLocation{876, 2614, 77}`. SystemUI uses this to place the UDFPS view and to decide whether a touch is on the sensor. The HAL itself ignores the x/y passed to `onPointerDown`.

**Which sysfs nodes LineageOS writes for UDFPS:** only `fod_enable,1,1,0` (init, once). The HAL reads `actual_mask_brightness`. Nothing writes `set_fod_rect`, `mask_brightness` or `mask_enable` on this device.

### 1.3 Older LineageOS approach (lineage-18.1 `hidl/fingerprint/inscreen`)

`android_hardware_samsung` lineage-18.1, `hidl/fingerprint/inscreen/include/samsung_fingerprint_inscreen.h`:

```c
#define FOD_ENABLE "fod_enable,1,1"
#define FOD_DISABLE "fod_enable,0"
// #define FOD_SET_RECT "set_fod_rect,554,2263,886,2595"
#define FINGERPRINT_ACQUIRED_VENDOR 6
#define VENDORCODE_FINGER_DOWN 9002
#define VENDORCODE_FINGER_UP 9001
#define TSP_CMD_PATH "/sys/class/sec/tsp/cmd"
```

In that older design the HAL told the UI "finger down/up" via `ACQUIRED_VENDOR` with vendorCodes 9002/9001 (from older Samsung TAs). It did not send `request(22)`. On the gts7xl TA, LineageOS later switched to `request_touch_event=true`. **Check on the device which vendorCode comes with your `acquired 6`.** droidian-fpd throws the vendorCode away (`src/androidfp.cpp` `acquired_cb(uint64_t, info, int32_t, void*)`). Patching it to log the code would show whether it is 10001 (CAPTURE_READY), 9002, etc.

### 1.4 A wrapper on top of the stock vendor lib (gustavo-hc sm8250-common)

https://github.com/gustavo-hc/android_device_samsung_sm8250-common, `fingerprint/BiometricsFingerprint.cpp` (an `ISehBiometricsFingerprint@3.0` reimplementation for S20-series):

```cpp
#define SEH_FINGER_STATE 22
#define SEH_PARAM_PRESSED 2
#define SEH_PARAM_RELEASED 1
#define SEH_AOSP_FQNAME "android.hardware.biometrics.fingerprint@2.3::IBiometricsFingerprint"
#define TSP_CMD_PATH "/sys/class/sec/tsp/cmd"
#define BRIGHTNESS_PATH "/sys/class/backlight/panel0-backlight/brightness"
...ctor:  set(TSP_CMD_PATH, "set_fod_rect,421,2025,659,2263");  set(TSP_CMD_PATH, "fod_enable,1,1,0");
onFingerDown(): save brightness; set(BRIGHTNESS_PATH, "331");
                sehRequest(SEH_FINGER_STATE, SEH_PARAM_PRESSED, stringToVec(SEH_AOSP_FQNAME), ...);
                restore brightness after 400 ms
onFingerUp():   sehRequest(SEH_FINGER_STATE, SEH_PARAM_RELEASED, ...);
sehRequest(cmd, inParam, inBuf) -> ss_fingerprint_request(cmd, input, 0, output, 10, inParam);
```

This confirms that `sehRequest(cmdId, inParam, …)` maps 1:1 to `ss_fingerprint_request(cmdId, …, param=inParam)`. It also shows the "boost backlight on finger-down" trick. The `set_fod_rect` values there are for the S20 (1080-wide), not the Tab.

### 1.5 TrebleDroid / phh GSI on the *stock* Samsung vendor HAL (closest analogue to Droidian)

`TrebleDroid/platform_frameworks_base` branch `android-15.0.0_r26-td`, `services/core/java/com/android/server/biometrics/AuthService.java` L905-930:

```java
if(samsungHasCmd("fod_enable") && (mSamsungFingerprint != null || mSamsungFingerprintAidl != null)) {
    samsungCmd("fod_enable,1,1,0");
    String actualMaskBrightnessPath = "/sys/class/lcd/panel/actual_mask_brightness";
    fodFileObserver = new FileObserver(actualMaskBrightnessPath, FileObserver.MODIFY) {
        public void onEvent(int event, String path) {
            ...
            int eventReq = "0".equals(actualMask) ? 1 /*released*/ : 2 /*pressed*/;
            mSamsungFingerprint.sehRequest(22 /* SEM_FINGER_STATE */, eventReq,
                    new java.util.ArrayList<Byte>(), (int retval, java.util.ArrayList<Byte> out) -> {});
```

It sends an **empty** `inBuf`. It also issues `sehRequest(6, 0, [])` (sensor status) and `sehRequest(32, 0, [])` ("sensor brightness value") for logging, and `fod_rect,…` (L1232). `samsungCmd()` (L1418) writes `/sys/devices/virtual/sec/tsp/cmd` and reads back `cmd_status` / `cmd_result`.

phh's trigger is the kernel mask-brightness notification. On the Tab S7+ that notification never fires (section 1.6), so phh GSIs most likely do not get UDFPS on this tablet. For Droidian you need to trigger from touch coordinates instead.

### 1.6 Kernel display side (why "full-brightness white screen" alone does nothing, and why the kernel won't help)

In `mukahraman/kernel_samsung_sm8250` (droidian), `techpack/display/msm/samsung/ANA38401_AMSA05RB06/dsi_panel_ANA38401_AMSA05RB06_wqxga_octa_cmd.dtsi` L168:

```
//samsung,support-optical-fingerprint;
```

LineageOS's `android_kernel_samsung_sm8250` (lineage-24.0) has the same line, imported from Samsung OSRC. So `vdd->support_optical_fingerprint == false` on the Tab S7+ panel, and:

* `sde_connector_pre_update_fod_hbm()` (`sde/sde_connector.c` ~L796-815, LineageOS "fod" plane property → `dsi_panel_set_fod_hbm()`) is skipped.
* `/sys/class/lcd/panel/actual_mask_brightness` (`ss_dsi_panel_sysfs.c` L4446-4459, L5254) reads `0` and is never `sysfs_notify`'d. That notify lives in `ss_dsi_panel_common.c` ~L6755 inside `if (vdd->support_optical_fingerprint)`.
* `/sys/class/lcd/panel/mask_enable` (L5255) and `mask_brightness` (L5253) exist and are writable, but they only take effect through the same disabled path. **Don't count on them.** Testing `echo 1 > mask_enable` and watching dmesg for `[FINGER MASK]` is harmless.

**Conclusion:** userspace has to illuminate the sensor spot (a white disc at max backlight). The HAL must then get `request(22,2)`; without it the TA never captures, however bright the screen is.

### 1.7 Binder details (for a client outside Android's framework)

Stock Samsung Android 11 vendor `.hal` (used on R-based Samsung trees: `me2151/android_device_samsung_c2q`, `erfanoabdi/android_device_samsung_a51`, `Lehkeda/android_device_samsung_m51`, `Kscope-Devices/android_device_phh_treble interfaces/vendor/samsung/.../3.0/ISehBiometricsFingerprint.hal`):

```
package vendor.samsung.hardware.biometrics.fingerprint@3.0;
import android.hardware.biometrics.fingerprint@2.1::IBiometricsFingerprint;
interface ISehBiometricsFingerprint extends android.hardware.biometrics.fingerprint@2.1::IBiometricsFingerprint {
    sehRequest(int32_t cmdId, int32_t inParam, vec<int8_t> inBuf) generates (int32_t retval, vec<int8_t> outBuf);
};
```

Your `lshal` shows only `@2.1` and `@3.0` registered (no `@2.2`/`@2.3`), which fits a 2.1 base. HIDL transaction codes are 1-based in inheritance order:

| code | method |
|---|---|
| 1 | setNotify |
| 2 | preEnroll |
| 3 | enroll |
| 4 | postEnroll |
| 5 | getAuthenticatorId |
| 6 | cancel |
| 7 | enumerate |
| 8 | remove |
| 9 | setActiveGroup |
| 10 | authenticate |
| **11** | **sehRequest** |

A decompiled Samsung `services.jar` proxy confirms code 11 (`488315/samsung_framework .../V3_0/ISehBiometricsFingerprint.java`): `writeInterfaceToken("vendor.samsung.hardware.biometrics.fingerprint@3.0::ISehBiometricsFingerprint"); writeInt32(cmd); writeInt32(param); writeInt8Vector(buf); transact(11, …)`.

Caveats:
* If the vendor were built on a 2.3 base (the gustavo-hc/a50 `.hal` variants are for Android 12+ builds), the code would be **14**. Check with `lshal debug` / `lshal -i`. You can also read `interfaceChain` (IBase code `256067662`) over gbinder and see whether `@2.3` appears.
* The reply order differs between sources. The decompiled Samsung proxy reads `int8 vector` then `int32`; phh's Java uses `(int retval, vec)`. For our purpose the reply can be ignored apart from the HIDL status word.

---

## 2. Does the TSP report finger-on-sensor events?

The gts7xl uses `CONFIG_TOUCHSCREEN_FTS1BA90A=y` (`arch/arm64/configs/vendor/samsung/gts7xl*.config`). Its DT is in `arch/arm64/boot/dts/samsung/drivers/input_gts7xl_common.dtsi` ~L501-523: `compatible = "stm,fts_touch"`, `stm,max_coords = <1751 2799>`, `stm,support_fod;`.

Driver: `drivers/input/touchscreen/stm/fts1ba90a/`.

* `fod_enable` (`fts_sec.c` L4580-4625): param0 sets/clears `FTS_MODE_PRESS` in `lowpower_flag` and writes it to the sponge, param1 sets `press_prop` ("fast"), and it calls `fts_set_fod_finger_merge()`. The third parameter in `fod_enable,1,1,0` is ignored by this driver.
* `set_fod_rect,l,t,r,b` (`fts_sec.c` L4653-4690): stored and written to sponge reg `0x4B`, re-applied on resume (`fts_ts.c` L3197). Values are validated against `display_x/y`. For the Tab: `set_fod_rect,799,2537,953,2691` (= 876±77, 2614±77).
* `fod_lp_mode,<n>` (L4554): keeps the touch IC in low-power FOD mode while the screen is off.
* Read-only attrs `fod_info` and `fod_pos` (`fts_sec.c` L799-800) return the sensor geometry from the touch IC firmware. These are useful for cross-checking 876/2614/77.
* **Event reporting** (`fts_ts.c` L2089-2108): a sponge gesture `FTS_SPONGE_EVENT_PRESS` with id `FOD_LONG/FOD_NORMAL` → `scrub_id = SPONGE_EVENT_TYPE_FOD (0x0F)`; `FOD_RELEASE` → `0x10`; `FOD_OUT` → `0x11`. Each one only does `sysfs_notify(&info->sec.fac_dev->kobj, NULL, "scrub_pos")` and logs `FOD PRESS` / `FOD RELEASE` / `FOD OUT`. **No `KEY_*` is emitted for FOD.** (`KEY_BLACK_UI_GESTURE`/`KEY_WAKEUP` are only for SPAY, double-tap and single-tap.)
* Reading `/sys/class/sec/tsp/scrub_pos` returns `"<id> <x> <y>"` and clears it (`fts_sec.c` L974-990). x/y are not filled for FOD events.
* There is no `input/fod_pressed` node in this driver. LineageOS's chown of it is generic.

**What the source can't settle:** whether the firmware raises FOD sponge events while the screen is on, or only in LP/AOD mode. That depends on the firmware. Test it like this:
`echo fod_enable,1,1,0 > /sys/class/sec/tsp/cmd; cat /sys/class/sec/tsp/cmd_result`, then `dmesg -w | grep -i fod` while pressing the sensor. In any case, normal `ABS_MT_POSITION_X/Y` events on `sec_touchscreen` keep flowing with the screen on. That makes a coordinate hit-test the most dependable trigger. Use `scrub_pos` POLLPRI as an optional or screen-off trigger.

---

## 3. Implementation plan for Droidian

### Option A (recommended first): standalone host helper `udfps-helper` (Python, libgbinder)

Droidian already packages `python3-gbinder` (Waydroid depends on it) and `python3-evdev`. Run it as root, or as a user with access to `/dev/hwbinder`, the input device and the sysfs nodes.

1. At start:
   * `echo "fod_enable,1,1,0" > /sys/class/sec/tsp/cmd`
   * optionally `echo "set_fod_rect,799,2537,953,2691" > /sys/class/sec/tsp/cmd`
   * check `/sys/class/sec/tsp/cmd_status` and `cmd_result`.
2. Open the `sec_touchscreen` evdev **without** `EVIOCGRAB`, so Phosh still gets the touches. Track MT slots (`ABS_MT_SLOT`, `ABS_MT_TRACKING_ID`, `ABS_MT_POSITION_X/Y`). Coordinates are raw portrait 0..1751 × 0..2799, independent of Phosh rotation. Hit-test `(x-876)²+(y-2614)² ≤ r²`, with r maybe 77–100 for tolerance.
3. Only arm while enroll or identify is active. You can tell from droidian-fpd's D-Bus signals on `org.droidian.fingerprint`, or by starting the helper from the enroll/unlock UI. A cheap first version arms permanently.
4. On finger enter:
   1. show the illumination: a white disc (or full white) at the sensor and max backlight via `/sys/class/backlight/panel0-backlight/brightness`. The droidian side can put a layer-shell overlay on top, e.g. a tiny GTK4 + gtk4-layer-shell window on the OVERLAY layer.
   2. wait about 30–100 ms (LineageOS waits up to 100 ms) for at least one frame to reach the panel.
   3. call `sehRequest(22, 2, [])`.
5. On finger leave: `sehRequest(22, 1, [])`, then remove the overlay and restore brightness.

Sketch (untested):

```python
import gbinder
DESC = "vendor.samsung.hardware.biometrics.fingerprint@3.0::ISehBiometricsFingerprint"
sm = gbinder.ServiceManager("/dev/hwbinder")
remote, status = sm.get_service_sync(DESC + "/default")
client = gbinder.Client(remote, DESC)

def seh_request(cmd, param):
    req = client.new_request()
    req.append_int32(cmd)
    req.append_int32(param)
    # empty vec<int8_t>: an empty hidl_string_vec is byte-identical on the wire
    # (libgbinder always writes the vec header buffer + a 0-length child buffer,
    #  see gbinder_writer_data_append_hidl_string_vec / append_hidl_vec)
    req.append_hidl_string_vec([])
    reply, st = client.transact_sync_reply(11, req)
    if reply is None or st != 0:
        return None
    hidl_status = reply.read_int32()      # HIDL reply starts with status (0 = OK)
    retval = reply.read_int32()           # may be ordered differently - see 1.7
    return hidl_status, retval

seh_request(22, 2)   # finger pressed
seh_request(22, 1)   # finger released
```

Bring-up checks before wiring it up:

* `seh_request(6, 0)` (sensor status) should return `100040` OK or `100041` WORKING. `seh_request(5, 0)` (sensor info) also exists, but it may need an outBuf. This pair proves the transport and code 11.
* Run `logcat -b all | grep -iE "bauth|fingerprint|sehRequest"` in the container while testing.

### Option B: patch droidian-fpd (cleaner long-term)

* `android/hybris/biometry_fp_hidl_for_hybris.cpp` (`fpHal = IBiometricsFingerprint::getService();` ~L235): add `u_hardware_biometry_sehRequest(int cmd, int param)`. It would do `ISehBiometricsFingerprint::castFrom(fpHal)` and call `sehRequest(cmd, param, {}, cb)`. This needs the Samsung `.hal` added to the Halium build tree (copy the 2.1-based `.hal` from §1.7) and a rebuild of the hybris compat lib. Alternatively, call it through libgbinder from the Linux side and skip the Android build.
* Also pass `vendorCode` through `acquired_cb`, which is currently dropped in `src/androidfp.cpp` (~L210). That makes it possible to react to `10001 CAPTURE_READY`, `10004 FINGER_LEAVE`, `1003 LIGHT_TOUCH`, and `1004/1005 TSP_BLOCK/UNBLOCK`.
* Add the touch hit-test and overlay hooks from Option A in `FPDCommunity` (`src/fpdcommunity.cpp`), or keep them in a separate helper that listens to fpd's D-Bus state.

### Risks and unknowns

* **Unverified on device:** whether the stock `@3.0-service` accepts `22` from a second process while droidian-fpd owns the session. It should, because HIDL services are multi-client and the call is stateless into `libbauthserver`. Code 11 vs 14 depends on the vendor's actual base version.
* **Illumination quality:** with no panel HBM mask, captures may be dim or noisy. Expect `ACQUIRED_VENDOR 1003` (light touch) or insufficient/partial results. Mitigations: max backlight (gustavo-hc uses 331 on S20, so check this panel's `max_brightness`), a pure-white disc with no compositor dimming, and a slightly longer delay before `22,2`. The TA may also want `SEM_REQUEST_OPTICAL_CALIBRATION (0x3F8)` / `FORCE_CBGE (21)`. LineageOS does not use them on gts7xl, so try them only if captures fail.
* **Rotation:** use raw evdev coordinates, not compositor coordinates. If you go with a layer-shell overlay, map the sensor point through the current output transform when drawing the disc.
* **Security:** anything that can reach `/dev/hwbinder` can drive the fingerprint HAL. Keep the helper root-only or in a dedicated group.
* **Burn-in:** keep the white disc and boosted backlight up only while a finger is on the sensor during an active enroll/identify, as LineageOS and gustavo-hc do (400 ms restore).
* **phh-style mask observer:** don't rely on `actual_mask_brightness` here. It never changes because optical-FP support is commented out in the panel DT.

---

## 4. Prior art on Linux-mobile (Droidian / Ubuntu Touch / postmarketOS)

* GitHub code search for `sehRequest`, `ISehBiometricsFingerprint`, `SEM_REQUEST_TOUCH_EVENT`, `fod_enable` and `onFingerDown`, filtered to droidian, ubports, halium, hybris, postmarketOS, furios and sailfish repos, returned **no hits**. The only matches are Android device trees, TrebleDroid/phh patches and decompiled Samsung frameworks.
* droidian-fpd (https://github.com/droidian/droidian-fpd) only uses the AOSP `@2.1` interface. It has no UDFPS or touch-event code.
* Web search found no report of a working Samsung UDFPS on Droidian, Ubuntu Touch or postmarketOS.
  * The UBports device page for Galaxy S10 (beyond1lte/beyond2lte, ultrasonic UDFPS) doesn't clearly claim the fingerprint works: https://devices.ubuntu-touch.io/device/beyond1lte/release/xenial
  * A UBports forum thread about a OnePlus in-display sensor points to an unofficial port: https://forums.ubports.com/post/91295
  * phh's gist on the lack of a generic UDFPS HAL: https://gist.github.com/phhusson/9c13e867f1160a5a59442b6d9d1e5311
  * Droidian's fingerprint-settings blog post: https://droidian.org/blog/state-of-droidian-week-36-2023/
* So I found no published Linux-mobile solution for Samsung UDFPS. This would be new work.

## Sources

* https://github.com/LineageOS/android_hardware_samsung (lineage-24.0: `aidl/fingerprint/{VendorConstants.h,LegacyHAL.cpp,Session.cpp,Fingerprint.cpp,fingerprint.sysprop}`, `fingerprint/UdfpsExtension.cpp`; lineage-18.1: `hidl/fingerprint/inscreen/*`)
* https://github.com/LineageOS/android_device_samsung_gts7xlwifi (`vendor.prop`, `BoardConfig.mk`, `device.mk`, `init/init.gts7xlwifi.rc`)
* https://github.com/LineageOS/android_device_samsung_sm8250-common (`init/init.fingerprint.rc`, `init/init.samsung.rc`, `init/init.samsung.display.rc`, `common.mk`)
* https://github.com/LineageOS/android_kernel_samsung_sm8250 and https://github.com/mukahraman/kernel_samsung_sm8250/tree/droidian (`drivers/input/touchscreen/stm/fts1ba90a/`, `techpack/display/msm/sde/sde_connector.c`, `techpack/display/msm/samsung/ss_dsi_panel_sysfs.c`, `.../ANA38401_AMSA05RB06/*.dtsi`, `arch/arm64/boot/dts/samsung/drivers/input_gts7xl_common.dtsi`)
* https://github.com/gustavo-hc/android_device_samsung_sm8250-common (`fingerprint/BiometricsFingerprint.cpp`, `interfaces/biometrics/fingerprint/3.0/ISehBiometricsFingerprint.hal`)
* https://github.com/TrebleDroid/platform_frameworks_base/blob/android-15.0.0_r26-td/services/core/java/com/android/server/biometrics/AuthService.java
* https://github.com/me2151/android_device_samsung_c2q/blob/HEAD/interfaces/biometrics/fingerprint/3.0/ISehBiometricsFingerprint.hal (2.1-based `.hal`)
* https://github.com/488315/samsung_framework (decompiled `ISehBiometricsFingerprint` proxy, transaction 11)
* AOSP `hardware/interfaces/biometrics/fingerprint/{2.1,2.2,2.3}/IBiometricsFingerprint.hal` (android.googlesource.com)
* https://github.com/mer-hybris/libgbinder (`src/gbinder_writer.c`), https://github.com/erfanoabdi/gbinder-python (`gbinder.pyx`)
* https://github.com/droidian/droidian-fpd

## Test log (19 Nov 2026, on device)
- `seh(6,0)` over hwbinder (txn 11, run as user) returned **100045**, so the transport works.
- Overlay: a gtk4-layer-shell disc only shows with `GSK_RENDERER=cairo` (the GL renderer draws nothing on hybris). Logical centre in portrait (transform 90) is (438,1307).
- Running `fingerprint/udfps-helper.py` while `Enroll` was in progress:
  - 63 finger-down `seh(22,2)` calls, all returning 0;
  - 61 `enrollresult_cb(fid=1, remaining=100)` callbacks plus `acquired 6` (VENDOR).
  - So the sensor captures on almost every touch, but `remaining` never drops below 100.
  - The suspected cause is that Samsung reports real progress or rejection reasons in the ACQUIRED_VENDOR **vendorCode**, which droidian-fpd throws away.
- `mask_enable=1` is accepted, but `actual_mask_brightness` stays 0 (no panel HBM mask; the DT optical-fp flag is off).
- `Abort` returned 2 while enrolling. Restarting droidian-fpd clears the state.
- **Next:** rebuild droidian-fpd with vendorCode logging and pass-through, then read the codes during capture.

---

# Addendum (2026-11-19): vendor event codes, `remaining=100`, and why samples don't count

Source reading only. No device was touched. Sources for this addendum:

* LineageOS `android_hardware_samsung` lineage-24.0 (`aidl/fingerprint/{VendorConstants.h,Session.cpp,Fingerprint.cpp}`) and its git history
* LineageOS `android_device_samsung_a51` (`fingerprint/BiometricsFingerprint.cpp`, `Android.mk`), an optical Samsung UDFPS on the same `libbauthserver` HAL style
* LineageOS `vendor.prop` of r8q, a52sxq and a72q
* Decompiled Samsung framework `488315/samsung_framework`. This is a recent One UI build, **not** the Android 11 build your vendor pairs with. Files:
  * `framework/sources/android/hardware/biometrics/BiometricFingerprintConstants.java`
  * `BiometricSettings/.../fingerprint/enroll/FingerprintEnrollActivity.java`
  * `services/.../fingerprint/{SemFpLocalHbmOpticalController,SemUdfpsOpticalHelper,SemFpScreenStatusNotifier,SemUdfpsHelper,SemFingerprintServiceExtImpl,SemFpOpticalClient}.java`
  * `services/.../fingerprint/hidl/{HidlToAidlCallbackConverter,SemHidlToAidlSehFingerprintAdapter}.java`

## A1. SEM_FINGERPRINT_EVENT_* codes (delivered as `acquired_info` / vendorCode > 10000)

Samsung's own table, `BiometricFingerprintConstants.java` (decompiled):

```java
SEM_FINGERPRINT_EVENT_BASE                  = 10000;
SEM_FINGERPRINT_EVENT_CAPTURE_READY         = 10001;
SEM_FINGERPRINT_EVENT_CAPTURE_STARTED       = 10002;
SEM_FINGERPRINT_EVENT_CAPTURE_COMPLETED     = 10003;
SEM_FINGERPRINT_EVENT_FINGER_LEAVE          = 10004;
SEM_FINGERPRINT_EVENT_CAPTURE_SUCCESS       = 10005;
SEM_FINGERPRINT_EVENT_CAPTURE_FAILED        = 10006;
SEM_FINGERPRINT_EVENT_FINGER_LEAVE_TIMEOUT  = 10007;
SEM_FINGERPRINT_EVENT_FACTORY_SNSR_SCRIPT_START = 10008;
SEM_FINGERPRINT_EVENT_FACTORY_SNSR_SCRIPT_END   = 10009;
SEM_FINGERPRINT_EVENT_INTERRUPT_CATCH       = 10011;
SEM_FINGERPRINT_EVENT_SWIPE_AUTHENTICATION  = 10012;
SEM_FINGERPRINT_EVENT_TOUCH_ENROLLMENT      = 10013;
SEM_FINGERPRINT_EVENT_GESTURE_SWIPE_UP/DOWN/DTAP/LPRESS = 20001/20002/20003/20004;
SEM_FINGERPRINT_EVENT_SPEN_CONTROL_ON/OFF   = 30001/30002;
SEM_FINGERPRINT_EVENT_AUTHENTICATION_FAILED_REASON_START..END = 40000..49999;
SEM_FINGERPRINT_EVENT_POINTER_UP            = 70001;
// acquired vendor codes (< 10000):
SEM_FINGERPRINT_ACQUIRED_WET_FINGER = 1001, DUPLICATED_IMAGE = 1002, LIGHT_TOUCH = 1003,
TSP_BLOCK = 1004, TSP_UNBLOCK = 1005, UNINTENDED_TOUCH = 1006;
// sensor status (reply of request 6):
SEM_SENSOR_STATUS_OK = 100040, WORKING = 100041, ERROR = 100042, CALIBRATION_ERROR = 100045;
```

`10010` does not appear in either source, and nothing exists between 10014 and 10020. LineageOS's `VendorConstants.h` has the same values, without 10011-10013 and 1006.

How Samsung's enroll UI reacts (`FingerprintEnrollActivity.java`, the `onAcquired` switch ~L276-450):

* **10001 CAPTURE_READY** resets the finger graphic (`setFingerStatus(0)`).
* **10002 CAPTURE_STARTED** sets `setFingerStatus(1)`.
* **10003 CAPTURE_COMPLETED** calls `mEnrollGuideFrame.completeCapture()`.
* **10004 FINGER_LEAVE** sets `mIsCalledFingerLeave = true`, finishes the scan and moves the guide frame to the next position.
* **10005 CAPTURE_SUCCESS** increments `mLogging_Ok++`, clears any error text, starts the "lift your finger" message and calls `setProgressResult(1)`, the success animation.
* **10006 CAPTURE_FAILED** calls `setProgressResult(3)` and `finishScan()`. It shows no specific error; the reason arrives as a separate standard acquired code.
* Vendor `1003` LIGHT_TOUCH shows "press harder" / `fingerprint_enroll_longer`. Vendor `1004` TSP_BLOCK shows a "touch blocked" message.

Reading your logs against this:

* With debounce, each touch gives `10004` (the leave from the *previous* touch) → `10001 → 10002 → 10003 → 10005` → `onEnrollResult`. So the TA did capture an image and judged the *capture* successful.
* Without debounce, `10006` + `acquired 5` (FINGERPRINT_ACQUIRED_TOO_FAST) means the `(22,1)` release reached the TA before the capture finished. The 400 ms debounce is correct. Samsung itself sends the release only on the real pointer-up; see A3.

## A2. What `remaining` means

`remaining` is a **percentage still to go**, counting down 100 → 0. It is not a sample count. `remaining == 100` means **0 % progress**.

The evidence:

1. **The Samsung framework passes the HAL value through untouched.** `hidl/HidlToAidlCallbackConverter.java` L98-99:
   ```java
   public final void onEnrollResult(int i, int i2, int i3, long j) {
       this.mAidlResponseHandler.onEnrollmentProgress(i, i3);   // i3 = remaining, unchanged
   ```
2. **Samsung's enroll UI turns it into a displayed percent with `100 - remaining`.** `FingerprintEnrollActivity.java` ~L452-474:
   ```java
   public final void onEnrollmentProgress(int i) {
       ...
       int i2 = 100 - i;                     // progress %
       if (i2 < 80) { /* log-curve smoothing of the displayed value */ }
       ...
       mTxtViewProgress.setText(... sec_fingerprint_percent_format, mCurrentPercent ...);
       mFinger_ProgressView.setPercent(mCurrentPercent);
   ```
3. **LineageOS leaves the value alone on SM8250 optical devices.** gts7xlwifi, r8q and a52sxq set no `ro.vendor.fingerprint.uses_percentage_samples` and no `force_calibrate`. `Session.cpp` L459-473 therefore forwards `samples_remaining` straight to AOSP's `onEnrollmentProgress()`, which expects a countdown to 0. Enrollment works there, so this TA counts down 100 → 0.
4. The `uses_percentage_samples` option (`Session.cpp` L460-462: `samples_remaining = 100 - samples_remaining`) exists for *older* Samsung TAs that report *progress* instead. It was introduced in commit 16d1a36 by Danny Wood, 2019, for the SM-A510F. It also appears as `TARGET_SEC_FP_USES_PERCENTAGE_SAMPLES` in `android_device_samsung_a51/fingerprint/Android.mk`. It does not apply to gts7xl.

So in your log, every capture is a successful capture that added **zero coverage** to the template. Enrollment ends when the TA reports `remaining=0` (`fid` stays 1 throughout). There is no separate progress message: progress arrives only through `onEnrollResult.remaining`.

## A3. Extra requests needed around captures?

From source, **LineageOS sends nothing beyond `22,2` / `22,1`** on gts7xl:

* `Session::enroll()` calls only `ss_fingerprint_enroll(&hat, userId, 0)`. `SEM_REQUEST_FORCE_CBGE (21, 1)` is sent only if `ro.vendor.fingerprint.force_calibrate` is set, and it is unset for gts7xlwifi and r8q.
* There is no per-capture request. `FINGERPRINT_REQUEST_ENROLL_SESSION 1002`, `ENROLL_TYPE 18` and `SESSION_OPEN 2` are defined in `VendorConstants.h` but never called.
* `onPointerDown` → `request(22, 2)`; `onPointerUp` → `request(22, 1)`. That is all.
* Older LineageOS a51 HAL: `onFingerDown()` boosts brightness to 331 after 35 ms and sends `request(SEM_REQUEST_TOUCH_EVENT, FINGERPRINT_REQUEST_SESSION_OPEN)`, i.e. `(22, 2)`. `onFingerUp()` sends `(22, FINGERPRINT_REQUEST_RESUME)`, i.e. `(22, 1)`. `postEnroll()` and `cancel()` also force `onFingerUp()`. An optional `waitForSensor()` loops on `request(6, 0)` until it returns `100040` OK. The a51 file names these constants differently, but the numbers match.

The Samsung framework does the same for the touch event. `SemFpLocalHbmOpticalController.handleTouchEventInLhbm()` (~L151-180):

```java
} else {
    ((FingerprintProvider) ...).semRequest(sensorId, 22, i, null, null);   // i = 2 down, 1 up
}
...
if (i == 1) ... onPointerUp(...)
```

For down (`i == 2`) it first waits until local-HBM is on (`mTouchDownDeliverAfterLhbmOn`). The "in-house" LHBM variant uses `semRequest(43, freezeBrightness, {i})`. That is for newer panels and not the Tab's 2020-era stack.

That framework also sends extra requests, but **their command numbers do not match LineageOS's table**, which came from older frameworks:

* `36` with param 2 = interactive, 1 = not (`SemFpScreenStatusNotifier`). LineageOS calls the screen-status request `SEM_REQUEST_SET_SCREEN_STATUS 0x3F0` (1008).
* `40` returns the "calibrated time" string (`SemUdfpsHelper` dump).
* `34` is a Qualcomm ultrasonic-only force-QDB request (`SemFingerprintServiceExtImpl.handleQcomForceQDB`).

These come from a newer One UI and cannot be safely mapped onto the Android 11 gts7xl TA. Since LineageOS gets working enrollment on gts7xl with only `22`, **no extra request appears to be required.** That is an inference from LineageOS working, not proof for the stock `@3.0-service` path.

## A4. Could captures be rejected for low brightness or quality?

Likely, but the source can't prove it. What can be said:

* **Expected rejection codes, if the TA reports them:**
  * standard `FINGERPRINT_ACQUIRED_PARTIAL (1)`, `INSUFFICIENT (2)`, `IMAGER_DIRTY (3)`, `TOO_FAST (5)`
  * vendor `SEM_FINGERPRINT_ACQUIRED_LIGHT_TOUCH (1003)`, `DUPLICATED_IMAGE (1002)`, `WET_FINGER (1001)`
  * event `10006 CAPTURE_FAILED`
  
  You get `10005` and no such code. The TA therefore accepts the image as a capture but extracts nothing usable, or merges it as zero new area. A dark or uniform optical image (no illumination, or only weak illumination) would fit that, since the TA sees "a capture" with no ridge detail. So would pressing the same spot repeatedly, but then 1002 DUPLICATED_IMAGE would be expected. This is inference.
* **How Samsung illuminates the sensor:** the framework never sends a brightness value to the TA. It draws a **mask** in SystemUI and drives the panel:
  * `SemUdfpsOpticalHelper.java` constants: `MAX_BRIGHTNESS_PATH = "/sys/class/lcd/panel/mask_brightness"`, `HW_LIGHT_SOURCE_PATH = "/sys/class/lcd/panel/fp_green_circle"` (`"1"` draw, `"0"` hide, only when `mIsSupportHwLightSource`), `DISPLAY_PANEL_TYPE_PATH = "sys/class/lcd/panel/window_type"`.
  * Fields `mBrightnessColor`, `mBrightnessColorForLowBrightness` and `mNits` show the mask uses a **specific colour at a specific luminance**, which the TA's factory calibration assumes. It is not plain white.
  * `OPTICAL_CALIBRATION_NORMAL = 1`, `OPTICAL_CALIBRATION_LOW_BRIGHTNESS = 2`.
  * `SemFpOpticalClient` in calibration mode just opens a SystemUI session that shows the mask with a `"nits"` colour string (command code 500 normal; the calibration code is obfuscated). It is a UI-side mask and not a HAL request.
* **`SEM_REQUEST_OPTICAL_CALIBRATION = 0x3F8` (1016)** exists only as a constant in LineageOS's `VendorConstants.h`. No open-source wrapper calls it, so its parameters are unknown. The same holds for `SEM_REQUEST_MASK_CTL = 0x3F5` (1013). **Don't send these blindly.** Recalibrating the TA from a white-screen state could overwrite factory calibration in `/efs/biometrics` (the directory created in `init.fingerprint.rc` / `init.gts7xlwifi.rc`).
* **`SEM_REQUEST_FORCE_CBGE (21, 1)`** is the safe calibration-ish request LineageOS uses on some devices: "background estimation", per commit f9eb478, which fixed "constant calibration error" after DSU. LineageOS commit d7e5b00 waits for `10001 CAPTURE_READY` after it. It is low risk to try once before `enroll()`, but nothing indicates gts7xl needs it.
* **On this panel the kernel HBM mask path is disabled** (`//samsung,support-optical-fingerprint;`, see §1.6), so `mask_brightness` / `actual_mask_brightness` do nothing. LineageOS gets working enrollment on gts7xl with SystemUI's normal UDFPS illumination: a bright circle drawn by the UI. Brightness and colour of your overlay are therefore the main variables.

## A5. Concrete next experiments (in order)

1. **Read the TA's own reason.** In the container run `logcat -b all -v time | grep -iE "bauth|fpsvc|fingerprint|goodix|gf_|sehRequest"` during one capture. libbauthserver/TA logs usually print image quality and coverage ("quality", "coverage", "score", "dark"). Grep for those terms too.
2. **Check that the sensor is idle and OK.** `sehRequest(6, 0)` should return `100040` before you start the enroll.
3. **Improve illumination:**
   * draw the disc **only** over the sensor (876, 2614, r≈77–100 px) on a black background, at maximum panel brightness (read `max_brightness` of the backlight device; gustavo-hc and a51 write 331);
   * show it **before** `22,2`; LineageOS waits up to 100 ms and a51 boosts 35 ms after down;
   * keep it up until after `10003`/`10005`;
   * try white, then a green-ish disc, since Samsung uses a calibrated colour.
4. **Move the finger between captures.** If coverage still never rises, look for `1002` in logcat.
5. If the TA log mentions calibration or background, try `sehRequest(21, 1)` once before `Enroll` and wait for `10001`, as LineageOS `force_calibrate` does. **Avoid 0x3F5, 0x3F8 and the newer-framework codes 36/40/43** unless logcat shows the TA expects them.
6. Make sure `(22,1)` is sent only after `10003`/`10005` or a real lift, never during a capture. That is the TOO_FAST (5) case.
