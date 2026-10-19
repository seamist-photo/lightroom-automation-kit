# Proprietary RAW: why "just use an open decoder" fails

> **Provenance note.** This page records findings from our own production
> workflow (Windows, Lightroom Classic 15.x, Nikon Z6 III HE-NEF files,
> October 2026). It is not covered by CI because reproducing it needs
> proprietary sample files. Treat the conclusion as a strong prior and verify
> against your own camera before designing a pipeline around it.

## The problem

Nikon's **HE** (high efficiency) NEF variant is a lossy-compressed RAW whose
entropy coding is not the classic NEF format. Everything downstream inherits
that: demosaicers, Linux raw pipelines, and bulk converters either refuse the
file or return a garbled image.

## What we observed

Attempting to decode HE-NEF outside Adobe's engine:

- **rawspeed** (the decoding library behind darktable and friends) does not
  recognise the compression variant and rejects the file.
- **libraw**-based tools reject it for the same reason.
- **darktable-cli**, which sits on top of both, cannot produce an image.
- Lightroom's own importer, Adobe Camera Raw, and Adobe DNG Converter handle it
  without complaint.

So the constraint is not "which open-source tool is better" - at the time of
testing, none of them could decode the format at all. This is a codec gap, not a
quality difference.

## What this means for automation

1. **Do not promise an open-source-only path for HE-RAW.** Any pipeline that
   must read the original pixels needs an Adobe component, or a camera setting
   change.
2. **The cheap fix is at capture time**: set the camera to standard (lossless
   compressed) NEF. Then the open ecosystem works and your automation stops
   depending on a commercial engine.
3. **DNG conversion is a viable escape hatch** when you already have the files:
   Adobe DNG Converter turns HE-NEF into DNG once, and everything downstream
   reads the DNG. It costs a full conversion pass and disk space.
4. **If you only need settings, you do not need the pixels.** Reading and
   writing develop parameters from the catalog or from `.xmp` sidecars works
   regardless of codec - see `catalog-sqlite.md` and `xmp-and-profiles.md`.

## How to reproduce the check on any camera

```bash
# 1. does a plain decoder see it at all?
darktable-cli input.nef out.jpg --width 800 2>&1 | head

# 2. what does the metadata layer say?
exiftool -Compression -CompressionType -RawImageDigest input.nef
```

If step 1 fails while step 2 reports a plausible compressed RAW, you are in the
same situation: the container is readable, the codec is not.
