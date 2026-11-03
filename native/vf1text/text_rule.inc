// ================================================================ the one text rule (patcher/vf1_text.py)
// Included by vf1text.cpp (vf1text.dll / vf1font.dll) and vf1fun.cpp, so the DLLs read and write a game string exactly
// as the patcher does (the shared Unicode spec's per-character write rule and per-sequence read rule):
//
//   WRITE, per character: a Windows-1252 character is its one byte, any other character is UTF-8, in the same string;
//   every non-ASCII character is UTF-8 when the mixed bytes would read back as different text (EncodeStored).
//   READ, per sequence: each well-formed UTF-8 sequence (shortest form, no surrogate, nothing past U+10FFFF) is its
//   character, every other byte is its Windows-1252 character (Decode).
//
// No C runtime: only the helpers the including file defines before this (none are needed here).

static const unsigned short Cp1252High[32] = {
    0x20AC, 0x0081, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6, 0x2030, 0x0160, 0x2039, 0x0152,
    0x008D, 0x017D, 0x008F, 0x0090, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122,
    0x0161, 0x203A, 0x0153, 0x009D, 0x017E, 0x0178,
};

// One UTF-8 sequence at s (n bytes left): its code point and length, or length 0 when malformed.
static int Utf8At(const unsigned char *s, int n, unsigned *cp) {
    if (n <= 0) return 0;
    unsigned c = s[0];
    if (c < 0x80) { *cp = c; return 1; }
    int len; unsigned min;
    if (c >= 0xC2 && c <= 0xDF) { len = 2; c &= 0x1F; min = 0x80; }
    else if (c >= 0xE0 && c <= 0xEF) { len = 3; c &= 0x0F; min = 0x800; }
    else if (c >= 0xF0 && c <= 0xF4) { len = 4; c &= 0x07; min = 0x10000; }
    else return 0;
    if (n < len) return 0;
    for (int i = 1; i < len; ++i) {
        if ((s[i] & 0xC0) != 0x80) return 0;
        c = (c << 6) | (s[i] & 0x3F);
    }
    if (c < min || c > 0x10FFFF || (c >= 0xD800 && c <= 0xDFFF)) return 0;
    *cp = c;
    return len;
}

static bool IsUtf8(const unsigned char *s, int n) {
    for (int i = 0; i < n;) {
        unsigned cp;
        int k = Utf8At(s + i, n - i, &cp);
        if (!k) return false;
        i += k;
    }
    return true;
}

static int Utf8Put(unsigned cp, unsigned char *out) {
    if (cp < 0x80) { out[0] = (unsigned char)cp; return 1; }
    if (cp < 0x800) { out[0] = (unsigned char)(0xC0 | (cp >> 6)); out[1] = (unsigned char)(0x80 | (cp & 0x3F)); return 2; }
    if (cp < 0x10000) {
        out[0] = (unsigned char)(0xE0 | (cp >> 12)); out[1] = (unsigned char)(0x80 | ((cp >> 6) & 0x3F));
        out[2] = (unsigned char)(0x80 | (cp & 0x3F)); return 3;
    }
    out[0] = (unsigned char)(0xF0 | (cp >> 18)); out[1] = (unsigned char)(0x80 | ((cp >> 12) & 0x3F));
    out[2] = (unsigned char)(0x80 | ((cp >> 6) & 0x3F)); out[3] = (unsigned char)(0x80 | (cp & 0x3F));
    return 4;
}

// The character a single byte reads as (Windows-1252; the five unassigned bytes as the Latin-1 control).
static unsigned SingleCp(unsigned b) { return (b >= 0x80 && b < 0xA0) ? Cp1252High[b - 0x80] : b; }

// The one byte that reads back as code point cp, or -1 when it has none.
static int SingleByteOf(unsigned cp) {
    if (cp < 0x80 || (cp >= 0xA0 && cp <= 0xFF)) return (int)cp;
    for (int i = 0; i < 32; ++i) if (Cp1252High[i] == cp) return 0x80 + i;
    return -1;
}

// A string as code points, by the per-sequence read rule. Returns the count; the caller gives room for n code points.
// The string is `whole` bytes long (at least n); only the characters that end within the first n bytes are returned
// (a counted draw hands over a piece of a longer string, and a character cut by the count is left out).
static int Decode(const unsigned char *s, int n, unsigned *out, unsigned char *widths, int whole = -1) {
    int count = 0;
    if (whole < n) whole = n;
    for (int i = 0; i < whole;) {
        unsigned cp;
        int k = Utf8At(s + i, whole - i, &cp);
        if (!k) { cp = SingleCp(s[i]); k = 1; }
        if (i + k > n) break;
        out[count] = cp; widths[count] = (unsigned char)k; ++count;
        i += k;
    }
    return count;
}

// cps[0..n) as stored bytes by the write rule, into out (room for 4 * n bytes); returns the byte count.
static int EncodeStored(const unsigned *cps, int n, unsigned char *out) {
    int m = 0;
    for (int i = 0; i < n; ++i) {
        int b = SingleByteOf(cps[i]);
        if (b >= 0) out[m++] = (unsigned char)b; else m += Utf8Put(cps[i], out + m);
    }
    int k = 0;
    bool same = true;
    for (int i = 0; i < m && same;) {                 // read back per sequence: the same text?
        unsigned cp;
        int w = Utf8At(out + i, m - i, &cp);
        if (!w) { cp = SingleCp(out[i]); w = 1; }
        if (k >= n || cps[k] != cp) same = false;
        ++k;
        i += w;
    }
    if (same && k == n) return m;
    m = 0;                                            // no: every non-ASCII character as UTF-8
    for (int i = 0; i < n; ++i) m += Utf8Put(cps[i], out + m);
    return m;
}
