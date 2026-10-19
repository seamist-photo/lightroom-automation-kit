# XMP: three different things that share a name

"Write an XMP" means three unrelated operations in Lightroom. Confusing them is
why a delivered preset "does not work" on the client's machine.

## 1. Paired sidecar - only for proprietary RAW

`<name>.xmp` next to `<name>.nef` / `.cr3` / `.arw`. It exists only when
*Catalog Settings → Metadata → Automatically write changes into XMP* is on, and
only for formats Lightroom cannot write into.

- One sidecar per photo, same basename, same folder.
- DNG, JPG, TIFF, PSD: **no sidecar** - settings are embedded in the file.
- Writing sliders into a sidecar is the safest bulk path: no plugin, no open
  Lightroom, and it is fully reversible.

With exiftool the develop keys use the `crs:` namespace:

```bash
exiftool -overwrite_original \
  -crs:Exposure2012=+0.45 -crs:Highlights2012=-32 -crs:Shadows2012=+18 \
  -crs:Temperature=5450 -crs:Tint=8 \
  /path/to/photo.xmp
```

## 2. Presets / profiles - a recipe, not a photo

Stored under the Camera Raw settings directories, not next to any image:

```
Windows: %APPDATA%\Adobe\CameraRaw\ImportedSettings\
         %APPDATA%\Adobe\CameraRaw\Settings\
macOS:   ~/Library/Application Support/Adobe/CameraRaw/Settings/
```

A preset is bound to **no** photo. This is the part people get wrong when
delivering work: Lightroom reads presets from **its own** settings directory and
does **not** read a `.xmp` dropped into the image folder. Copying a preset next
to the photos does nothing.

## 3. Embedded - DNG and rendered formats

DNG carries the develop settings **as parameters** inside the container; it is
not a rendered pixel file. Opening it in Lightroom shows the edit and lets it be
changed. JPG/TIFF/PSD get their settings stored in the file's metadata block.

Practical consequence: "convert to DNG" is not "burn in the edit". If a client
needs a fixed look with no dependency on installed presets, export a TIFF/JPG -
do not hand over a DNG and expect it to look the same on a machine without the
profile.

## Delivering a look to someone else

A custom profile referenced by a preset is not self-contained. If the receiver
does not have the profile installed, Lightroom shows **"Profile missing"** and
falls back to Adobe Standard - the photo still opens, just wrong.

Two delivery shapes that actually work:

1. **Bundle** the `.xmp` profiles with a DNG in a zip and tell them to use
   *File → Import Profiles & Presets*, or copy into `ImportedSettings`.
2. **Flatten**: export TIFF or JPG so the look is baked into pixels.

After importing a profile, Lightroom matches it by UUID, so colour is correct
without further steps.
