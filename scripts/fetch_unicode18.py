"""Fetch and verify the Unicode 18.0 data and the open fonts Render Unicode with In-Game Fonts and Use Unicode Font
ship (the owner, 2026-11-03: "yeah you can add them! to all the games!", "as long as the unicode LOOKS similar to the
in-game fonts"). The same sources, versions and checks as the Virtual Villagers patcher's
scripts/fetch_unicode18_fonts.py and build_unicode18_tables.py.

Every run downloads into a NEW, empty folder of its own (--into, outside the repository: downloads are untrusted
data, read only as bytes and text here) and checks each file before anything is copied:

* GNU Unifont 18.0.01 (unifont / unifont_upper .otf, and the source archive for its two licence files): the GNU
  maintainer's OpenPGP signature, verified with gpg against the GNU keyring in a home folder of its own;
* Unicode's Last Resort 18.000 (High Efficiency): the SHA-256 GitHub publishes for the release asset;
* Noto Sans Cuneiform v2.001 and Noto Serif Tangut v2.170 (notofonts GitHub releases): the SHA-256 GitHub
  publishes when it does, and in every case the archive's SHA-256 recorded below (EXPECTED);
* the Unicode Character Database 18.0.0 files the tables are made from (unicode.org/Public/18.0.0), and the Unicode
  licence: each file's SHA-256 against EXPECTED (unicode.org publishes no signatures).

EXPECTED holds the SHA-256 of every file as first fetched and verified (2026-11-02, the Virtual Villagers patcher's
data/unicode18/SOURCES.json and assets/unicode_fonts/SOURCES.json); a file that differs stops the run.
Then the fonts and licences go to patcher/payload/UnicodeFonts/ (with SOURCES.json) and
scripts/build_vf1_unicode18.py makes patcher/vf1_unicode18_data.py from the UCD files.

Usage:  python scripts/fetch_unicode18.py --into C:/vf1/dl-u18-<date>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONTS_OUT = ROOT / "patcher" / "payload" / "UnicodeFonts"
GPG = Path(r"C:\Program Files\Git\usr\bin\gpg.exe")
UNIFONT = "18.0.01"
UNIFONT_BASE = f"https://ftp.gnu.org/gnu/unifont/unifont-{UNIFONT}/"
GNU_KEYRING = "https://ftp.gnu.org/gnu/gnu-keyring.gpg"
LAST_RESORT_API = "https://api.github.com/repos/unicode-org/last-resort-font/releases/tags/18.000"
LAST_RESORT_LICENSE = "https://raw.githubusercontent.com/unicode-org/last-resort-font/18.000/LICENSE"
NOTO = (("notofonts/cuneiform", "NotoSansCuneiform-v2.001",
         "NotoSansCuneiform/unhinted/otf/NotoSansCuneiform-Regular.otf", "NotoSansCuneiform-OFL-1.1.txt"),
        ("notofonts/tangut", "NotoSerifTangut-v2.170", "NotoSerifTangut/unhinted/otf/NotoSerifTangut-Regular.otf",
         "NotoSerifTangut-OFL-1.1.txt"))
UCD_BASE = "https://www.unicode.org/Public/18.0.0/"
UCD_FILES = ("ucd/UnicodeData.txt", "ucd/emoji/emoji-data.txt", "ucd/EastAsianWidth.txt", "ucd/Blocks.txt")
UNICODE_LICENSE = "https://www.unicode.org/license.txt"

EXPECTED = {
    "unifont-18.0.01.otf": "88D0A14D4AA9A96419720B39BA5DA921A59560D76D4EC7D523ACC06ED85CD3C2",
    "unifont_upper-18.0.01.otf": "472201E45A050BFF4C7658208B8C73E34EBCE3764B287A5A46C7774038EF9391",
    "Unifont-GPL-2.0-COPYING.txt": "CD2785C2B8E0A01D203560265B2D2D47CDB1401D2707D25918AC5531BCDBA947",
    "Unifont-OFL-1.1.txt": "869692AF094C57FB7258C57FE26820C759319603321D0FFEB278DE3651763DED",
    "LastResortHE-Regular.ttf": "CB7C2262CB86A33E7BDFABD0A51746E738B0DD10924126C4530C414C5FC7E4B6",
    "LastResort-OFL-1.1.txt": "FC8FC512B27846BDB0D6645BED8069AC87EA599548B58A8D04BC3B0EA705A9C4",
    "NotoSansCuneiform-v2.001.zip": "B686250DD8AB4DEFA9900236BB6E31F1F6FBE9E3C3B70E777272CEC1CD26BD27",
    "NotoSansCuneiform-Regular.otf": "AC997E70013545B311A1703EACD3D8DEA080B7B9E17924A69391A6F568B9C023",
    "NotoSansCuneiform-OFL-1.1.txt": "83E16AED35737EA80911A82938AD4BFE762FDE24928010C2C80D21ECE07BEC14",
    "NotoSerifTangut-v2.170.zip": "741EF7BCA66790C51C5F2EFEA3C291F5A82CC2E3992D9413A020AEC26DBD75B1",
    "NotoSerifTangut-Regular.otf": "CA10571246BDCE735FAC2698E875D86ED73354C76C650BB92C4D7CB43973AED6",
    "NotoSerifTangut-OFL-1.1.txt": "BD8B32C064BE2225D55F878A689063C6F169CCD9E2792D7051F0D74CF4816F1B",
    "ucd/UnicodeData.txt": "0736451DE439AE7BAF1425136617DA495E09EE5AFBE6E394374DB7009EA08950",
    "ucd/emoji/emoji-data.txt": "80D00F8E616A0EF27FD6B8DE3B758C06383B5D917E2977709578E68BAF733BF1",
    "ucd/EastAsianWidth.txt": "A0CF29EACD00CFCAEC4381C6B7C281685F18DBB4E7FF82B4076CCB342CA839AA",
    "ucd/Blocks.txt": "A58F8D322F3C5E254F9F97B1CBF76A454A7E02DE6AC35619A5E4F27AAABFD553",
    "license.txt": "E7A93B009565CFCE55919A381437AC4DB883E9DA2126FA28B91D12732BC53D96",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def get(url: str, dest: Path) -> bytes:
    print("fetch", url)
    req = urllib.request.Request(url, headers={"User-Agent": "VF1FP-unicode18-fetch"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return data


def expect(name: str, data: bytes) -> None:
    want = EXPECTED.get(name)
    if want and want != sha(data):
        raise SystemExit(f"{name}: SHA-256 {sha(data)} is not the recorded {want} -- nothing was copied")


def _posix(p: Path) -> str:
    s = str(p).replace("\\", "/")
    return "/" + s[0].lower() + s[2:] if s[1:2] == ":" else s


def verify_signature(folder: Path, file: Path, sig: Path, keyring: Path) -> None:
    home = folder / "gnupg-home"
    home.mkdir(exist_ok=True)
    r = subprocess.run([str(GPG), "--homedir", _posix(home), "--batch", "--no-default-keyring", "--keyring",
                        _posix(keyring), "--verify", _posix(sig), _posix(file)], capture_output=True, text=True)
    print(r.stderr.strip())
    if r.returncode != 0 or "Good signature" not in r.stderr:
        raise SystemExit(f"{file.name}: the OpenPGP signature does not verify -- nothing was copied")


def release(api: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(api, headers={"User-Agent": "VF1FP"}), timeout=60) as r:
        return json.loads(r.read())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--into", type=Path, required=True, help="a new, empty folder outside the repository")
    a = ap.parse_args(argv)
    folder = a.into.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    record: dict = {"note": "The open fonts vf1text.dll and vf1font.dll load privately (AddFontMemResourceEx) as the "
                            "last steps of their fallback chain; fetched and verified by scripts/fetch_unicode18.py.",
                    "files": {}}
    placed: dict[str, bytes] = {}
    keyring = folder / "gnu-keyring.gpg"
    get(GNU_KEYRING, keyring)
    tar_name = f"unifont-{UNIFONT}.tar.gz"
    for name in (f"unifont-{UNIFONT}.otf", f"unifont_upper-{UNIFONT}.otf", tar_name):
        data = get(UNIFONT_BASE + name, folder / name)
        get(UNIFONT_BASE + name + ".sig", folder / (name + ".sig"))
        verify_signature(folder, folder / name, folder / (name + ".sig"), keyring)
        if name != tar_name:
            expect(name, data)
            placed[name] = data
            record["files"][name] = {"source": UNIFONT_BASE + name, "version": f"GNU Unifont {UNIFONT}",
                                     "verified": f"OpenPGP signature {UNIFONT_BASE}{name}.sig (GNU keyring)",
                                     "license": "GPL-2.0-or-later WITH Font-exception-2.0 OR OFL-1.1",
                                     "sha256": sha(data), "bytes": len(data)}
    wanted = {"OFL-1.1.txt": "Unifont-OFL-1.1.txt", "COPYING": "Unifont-GPL-2.0-COPYING.txt"}
    with tarfile.open(folder / tar_name, "r:gz") as tar:          # read by name, never extracted
        for member in tar.getmembers():
            base = member.name.rsplit("/", 1)[-1]
            if member.isfile() and base in wanted and member.name.count("/") == 1:
                data = tar.extractfile(member).read()
                expect(wanted[base], data)
                placed[wanted[base]] = data
                record["files"][wanted[base]] = {"source": f"{UNIFONT_BASE}{tar_name} ({member.name})",
                                                 "sha256": sha(data), "bytes": len(data)}
    rel = release(LAST_RESORT_API)
    asset = next(x for x in rel["assets"] if x["name"] == "LastResortHE-Regular.ttf")
    data = get(asset["browser_download_url"], folder / "lastresort" / asset["name"])
    published = (asset.get("digest") or "").removeprefix("sha256:").upper()
    if not published or published != sha(data):
        raise SystemExit(f"{asset['name']}: SHA-256 {sha(data)} is not the published {published!r}")
    expect(asset["name"], data)
    placed[asset["name"]] = data
    record["files"][asset["name"]] = {"source": asset["browser_download_url"], "version": "Last Resort 18.000",
                                      "verified": "SHA-256 published for the release asset", "license": "OFL-1.1",
                                      "sha256": sha(data), "bytes": len(data)}
    lic = get(LAST_RESORT_LICENSE, folder / "lastresort" / "LICENSE")
    expect("LastResort-OFL-1.1.txt", lic)
    placed["LastResort-OFL-1.1.txt"] = lic
    record["files"]["LastResort-OFL-1.1.txt"] = {"source": LAST_RESORT_LICENSE, "sha256": sha(lic), "bytes": len(lic)}
    for repo, tag, member, licence in NOTO:
        rel = release(f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
        asset = next(x for x in rel["assets"] if x["name"] == tag + ".zip")
        data = get(asset["browser_download_url"], folder / tag / asset["name"])
        published = (asset.get("digest") or "").removeprefix("sha256:").upper()
        if published and published != sha(data):
            raise SystemExit(f"{asset['name']}: SHA-256 {sha(data)} is not the published {published}")
        expect(asset["name"], data)
        with zipfile.ZipFile(folder / tag / asset["name"]) as z:     # read by name, never extracted
            font = z.read(member)
            ofl = next(z.read(n) for n in z.namelist() if n.rsplit("/", 1)[-1] == "OFL.txt")
        name = member.rsplit("/", 1)[-1]
        expect(name, font)
        expect(licence, ofl)
        placed[name], placed[licence] = font, ofl
        record["files"][name] = {"source": f"{asset['browser_download_url']} ({member})", "version": tag,
                                 "verified": ("SHA-256 published for the release asset" if published else
                                              "the archive's recorded SHA-256 (no checksum is published)"),
                                 "archive_sha256": sha(data), "license": "OFL-1.1", "sha256": sha(font),
                                 "bytes": len(font)}
        record["files"][licence] = {"source": f"{asset['browser_download_url']} (OFL.txt)", "sha256": sha(ofl),
                                    "bytes": len(ofl)}
    for name in UCD_FILES:
        expect(name, get(UCD_BASE + name, folder / "ucd18" / name))
    expect("license.txt", get(UNICODE_LICENSE, folder / "ucd18" / "license.txt"))
    FONTS_OUT.mkdir(parents=True, exist_ok=True)
    for name, data in placed.items():
        (FONTS_OUT / name).write_bytes(data)
    (FONTS_OUT / "SOURCES.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("placed", sorted(placed), "UCD in", folder / "ucd18")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
