"""Turn a folder of phone recordings into a Smash Ultimate voice-bank mod.

    .venv\\Scripts\\python.exe voice_packs\\build_voice_pack.py ^
        --takes "C:\\path\\to\\recordings" ^
        --order voice_packs\\wiifit\\RECORDING_ORDER.txt ^
        --template voice_packs\\wiifit\\template\\vc_wiifit_template.nus3audio ^
        --name "WiiFit_MyVoice"

Stages (each resumable; use --stage to stop early):
  1. order   — sort the takes by their number ("Name.m4a" is take 1,
               "Name 2.m4a" is take 2, …) and pair the Nth take with the
               Nth clip name in RECORDING_ORDER.txt.
  2. wav     — ffmpeg (bundled with imageio-ffmpeg): mono 48 kHz WAV,
               silence trimmed off both ends, loudness levelled.
  3. lopus   — clip encoding.  Default --codec idsp: Nintendo ADPCM via
               tools/audio/VGAudioCli.exe (what the template's clips are;
               the 2018 CLI release has no Opus).  --codec lopus: Switch
               Opus via ffmpeg's libopus + a Python container writer.
  4. bank    — nus3audio: replace every clip of the template bank by
               index, write vc_wiifit_c00 … c07 into a mod folder
               (tools/audio/nus3audio.exe).

Output: voice_packs/<fighter>/out/<name>/sound/bank/fighter_voice/*.nus3audio
— copy that <name> folder to sd:/ultimate/mods/ (or install it with Smash
Night) and the voice is live on every costume slot.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools", "audio")
NUS3AUDIO = os.path.join(TOOLS, "nus3audio.exe")
VGAUDIO = os.path.join(TOOLS, "VGAudioCli.exe")
AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aac", ".ogg", ".flac", ".caf"}


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def read_order(path):
    names = []
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*(\d+)\.\s+(\S+)", line)
        if m:
            names.append(m.group(2))
    if not names:
        sys.exit(f"no clip names found in {path}")
    return names


def take_number(filename):
    stem = os.path.splitext(filename)[0]
    m = re.search(r"(\d+)\s*$", stem)
    return int(m.group(1)) if m else 1


def list_takes(folder):
    files = [f for f in os.listdir(folder)
             if os.path.splitext(f)[1].lower() in AUDIO_EXTS]
    files.sort(key=take_number)
    nums = [take_number(f) for f in files]
    if nums != list(range(1, len(files) + 1)):
        sys.exit(f"take numbers are not 1..{len(files)} in order: {nums}")
    return [os.path.join(folder, f) for f in files]


def run(cmd, what):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"{what} failed ({r.returncode}):\n{' '.join(cmd)}\n"
                 f"{r.stdout[-800:]}\n{r.stderr[-800:]}")
    return r


def to_wav(src, dst, ff):
    # trim silence from both ends, level to a consistent loudness
    af = ("silenceremove=start_periods=1:start_threshold=-40dB:"
          "start_silence=0.05,areverse,"
          "silenceremove=start_periods=1:start_threshold=-40dB:"
          "start_silence=0.08,areverse,"
          "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000")
    run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
         "-vn", "-ac", "1", "-ar", "48000", "-af", af, "-c:a", "pcm_s16le",
         dst], "ffmpeg")


# ── Switch Opus ("lopus", Namco header) written in Python ────────────
# The VGAudioCli *release* (2.2.1, 2018) predates its Opus support, so the
# encoder is ffmpeg's libopus (via imageio-ffmpeg) and the Nintendo
# container is written here, byte-for-byte as VGAudio's NxOpusWriter does:
#   Namco header, big-endian, 0x40 bytes:
#     "OPUS", 0, sampleCount, channels, sampleRate, loopStart, loopEnd,
#     flags (0x10 = looping), 0x40, standardFileSize, zero padding
#   standard header, little-endian, 0x28 bytes:
#     0x80000001, 0x18, u8 version=0, u8 channels, u16 frameLen+8 (0 if
#     the frames differ in size), u32 sampleRate, 0x20, 0, 0, u16 preSkip,
#     u16 0, 0x80000004, u32 dataSize
#   data, big-endian: per frame u32 length, u32 finalRange, bytes
# 64 kbps CBR, 20 ms frames — the shape of the game's own voice clips.

def ogg_packets(data):
    """Yield the packets of an Ogg stream (page/segment reassembly)."""
    pos, pending = 0, b""
    while pos + 27 <= len(data):
        if data[pos:pos + 4] != b"OggS":
            raise ValueError("not an Ogg stream")
        nseg = data[pos + 26]
        lacing = data[pos + 27:pos + 27 + nseg]
        body = pos + 27 + nseg
        for seg in lacing:
            pending += data[body:body + seg]
            body += seg
            if seg < 255:
                yield pending
                pending = b""
        pos = body


def wav_sample_count(path):
    import wave
    with wave.open(path, "rb") as w:
        return w.getnframes(), w.getnchannels(), w.getframerate()


def to_idsp(src, dst):
    """Nintendo DSP-ADPCM in an IDSP container via VGAudioCli (the 2.2.1
    release handles IDSP; it predates Opus).  This is what the template
    bank's own clips are, so it is the proven path."""
    run([VGAUDIO, "-i", src, "-o", dst], "VGAudioCli")


def to_lopus(src, dst, ff, bitrate=64000, frame_ms=20):
    import struct, tempfile
    samples, channels, rate = wav_sample_count(src)
    tmp = dst + ".ogg"
    run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
         "-c:a", "libopus", "-b:a", str(bitrate), "-vbr", "off",
         "-frame_duration", str(frame_ms), "-application", "audio",
         "-f", "ogg", tmp], "ffmpeg (libopus)")
    packets = list(ogg_packets(open(tmp, "rb").read()))
    os.remove(tmp)
    head = packets[0]
    if head[:8] != b"OpusHead":
        raise ValueError("no OpusHead in encoder output")
    pre_skip = struct.unpack_from("<H", head, 10)[0]
    frames = [p for p in packets[2:]]            # skip OpusHead, OpusTags
    frame_len = len(frames[0]) if frames and all(len(f) == len(frames[0]) for f in frames) else 0
    data_size = sum(len(f) + 8 for f in frames)
    std_size = 0x28 + data_size
    with open(dst, "wb") as out:
        namco = struct.pack(">4sIIIIIIIII", b"OPUS", 0, samples, channels, rate,
                            0, 0, 0, 0x40, std_size)
        out.write(namco.ljust(0x40, b"\0"))
        out.write(struct.pack("<IIBBHIIIIHH", 0x80000001, 0x18, 0, channels,
                              (frame_len + 8) if frame_len else 0, rate,
                              0x20, 0, 0, pre_skip, 0))
        out.write(struct.pack("<II", 0x80000004, data_size))
        for f in frames:
            out.write(struct.pack(">II", len(f), 0))
            out.write(f)
    return len(frames)


def build_bank(template, lopus_files, out_path):
    cmd = [NUS3AUDIO, template]
    for i, f in enumerate(lopus_files):
        cmd += ["-r", str(i), f]
    cmd += ["-w", out_path]
    run(cmd, "nus3audio")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--takes", required=True, help="folder of recordings")
    ap.add_argument("--order", required=True, help="RECORDING_ORDER.txt")
    ap.add_argument("--template", required=True, help="a vanilla-layout .nus3audio")
    ap.add_argument("--name", default="WiiFit_MyVoice", help="mod folder name")
    ap.add_argument("--fighter", default="wiifit")
    ap.add_argument("--slots", default="00,01,02,03,04,05,06,07")
    ap.add_argument("--stage", choices=["order", "wav", "lopus", "bank"],
                    default="bank", help="stop after this stage")
    ap.add_argument("--codec", choices=["idsp", "lopus"], default="idsp",
                    help="clip format: idsp (VGAudioCli, proven) or lopus "
                         "(Switch Opus written in Python)")
    a = ap.parse_args()

    names = read_order(a.order)
    takes = list_takes(a.takes)
    if len(takes) != len(names):
        sys.exit(f"{len(takes)} recordings but {len(names)} clips in the order file")
    print(f"== {len(takes)} takes matched to {len(names)} clips")
    for n, (t, name) in enumerate(zip(takes, names), 1):
        print(f"  {n:2d}. {os.path.basename(t)}  ->  {name}")
    if a.stage == "order":
        return

    work = os.path.join(HERE, a.fighter, "work")
    wav_dir, lopus_dir = os.path.join(work, "wav"), os.path.join(work, "lopus")
    os.makedirs(wav_dir, exist_ok=True); os.makedirs(lopus_dir, exist_ok=True)
    ff = ffmpeg()
    print("== converting to 48 kHz mono WAV (trimmed, levelled)")
    wavs = []
    for t, name in zip(takes, names):
        dst = os.path.join(wav_dir, name + ".wav")
        if not os.path.isfile(dst) or os.path.getmtime(dst) < os.path.getmtime(t):
            to_wav(t, dst, ff)
        wavs.append(dst)
    print(f"   {len(wavs)} WAVs in {wav_dir}")
    if a.stage == "wav":
        return

    if a.codec == "idsp":
        if not os.path.isfile(VGAUDIO):
            sys.exit(f"missing {VGAUDIO} — download VGAudioCli.exe from "
                     "https://github.com/Thealexbarney/VGAudio/releases")
        print("== encoding to IDSP (Nintendo ADPCM) with VGAudioCli")
    else:
        print("== encoding to Switch Opus (lopus, Namco header; 64 kbps CBR, 20 ms frames)")
    lopus = []
    for w in wavs:
        dst = os.path.join(lopus_dir, os.path.basename(w)[:-4] + "." + a.codec)
        if not os.path.isfile(dst) or os.path.getmtime(dst) < os.path.getmtime(w):
            if a.codec == "idsp":
                to_idsp(w, dst)
            else:
                to_lopus(w, dst, ff)
        lopus.append(dst)
    print(f"   {len(lopus)} clips in {lopus_dir}")
    if a.stage == "lopus":
        return

    if not os.path.isfile(NUS3AUDIO):
        sys.exit(f"missing {NUS3AUDIO} — download nus3audio.exe from "
                 "https://github.com/jam1garner/nus3audio-rs/releases")
    out = os.path.join(HERE, a.fighter, "out", a.name,
                       "sound", "bank", "fighter_voice")
    os.makedirs(out, exist_ok=True)
    bank = os.path.join(work, f"vc_{a.fighter}.nus3audio")
    print("== building the voice bank")
    build_bank(a.template, lopus, bank)
    for slot in a.slots.split(","):
        shutil.copy2(bank, os.path.join(out, f"vc_{a.fighter}_c{slot.strip()}.nus3audio"))
    mod_dir = os.path.join(HERE, a.fighter, "out", a.name)
    print(f"== done: {mod_dir}")
    print("   copy that folder to sd:/ultimate/mods/ (or install it with Smash Night)")


if __name__ == "__main__":
    main()
