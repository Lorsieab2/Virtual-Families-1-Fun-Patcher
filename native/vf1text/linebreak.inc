// Line breaking without ICU (wrap.inc): the CJK basics of UAX #14, the same table as patcher/vf1_line_break.py
// (FALLBACK_RANGES; tests/test_line_break.py checks the two are equal). Used only where Windows has no icu.dll
// (before Windows 10 1903).
//   LbIdeographic: a letter of a script written without spaces (ideographs, kana, Hangul, Yi, Thai, Lao, Myanmar,
//                  Khmer and the other SA scripts, emoji): a line may break before and after it;
//   LbClosing:     closing punctuation and the Japanese small kana, iteration marks and the long vowel mark (UAX #14
//                  CL, CP, EX, IS, NS, CJ): no line starts with it;
//   LbOpening:     opening punctuation (UAX #14 OP): no line ends with it.

enum { LbOther = 0, LbIdeographic = 1, LbClosing = 2, LbOpening = 3 };

struct LbRange { unsigned first, last; unsigned char cls; };
static const LbRange FallbackRanges[] = {   // sorted, not overlapping
    { 0x0021, 0x0021, LbClosing }, { 0x0028, 0x0028, LbOpening }, { 0x0029, 0x0029, LbClosing },
    { 0x002C, 0x002C, LbClosing }, { 0x002E, 0x002E, LbClosing }, { 0x003A, 0x003B, LbClosing },
    { 0x003F, 0x003F, LbClosing }, { 0x005B, 0x005B, LbOpening }, { 0x005D, 0x005D, LbClosing },
    { 0x007B, 0x007B, LbOpening }, { 0x007D, 0x007D, LbClosing },
    { 0x0E00, 0x0EFF, LbIdeographic }, { 0x1000, 0x109F, LbIdeographic }, { 0x1100, 0x115F, LbIdeographic },
    { 0x1780, 0x17FF, LbIdeographic }, { 0x1950, 0x19DF, LbIdeographic }, { 0x1A20, 0x1AAF, LbIdeographic },
    { 0x2018, 0x2018, LbOpening }, { 0x2019, 0x2019, LbClosing }, { 0x201C, 0x201C, LbOpening },
    { 0x201D, 0x201D, LbClosing }, { 0x2E80, 0x2FFF, LbIdeographic },
    { 0x3000, 0x3000, LbIdeographic }, { 0x3001, 0x3002, LbClosing }, { 0x3003, 0x3004, LbIdeographic },
    { 0x3005, 0x3005, LbClosing }, { 0x3006, 0x3007, LbIdeographic }, { 0x3008, 0x3008, LbOpening },
    { 0x3009, 0x3009, LbClosing }, { 0x300A, 0x300A, LbOpening }, { 0x300B, 0x300B, LbClosing },
    { 0x300C, 0x300C, LbOpening }, { 0x300D, 0x300D, LbClosing }, { 0x300E, 0x300E, LbOpening },
    { 0x300F, 0x300F, LbClosing }, { 0x3010, 0x3010, LbOpening }, { 0x3011, 0x3011, LbClosing },
    { 0x3012, 0x3013, LbIdeographic }, { 0x3014, 0x3014, LbOpening }, { 0x3015, 0x3015, LbClosing },
    { 0x3016, 0x3016, LbOpening }, { 0x3017, 0x3017, LbClosing }, { 0x3018, 0x3018, LbOpening },
    { 0x3019, 0x3019, LbClosing }, { 0x301A, 0x301A, LbOpening }, { 0x301B, 0x301B, LbClosing },
    { 0x301C, 0x301C, LbClosing }, { 0x301D, 0x301D, LbOpening }, { 0x301E, 0x301F, LbClosing },
    { 0x3020, 0x303A, LbIdeographic }, { 0x303B, 0x303C, LbClosing }, { 0x303D, 0x3040, LbIdeographic },
    { 0x3041, 0x3041, LbClosing }, { 0x3042, 0x3042, LbIdeographic }, { 0x3043, 0x3043, LbClosing },
    { 0x3044, 0x3044, LbIdeographic }, { 0x3045, 0x3045, LbClosing }, { 0x3046, 0x3046, LbIdeographic },
    { 0x3047, 0x3047, LbClosing }, { 0x3048, 0x3048, LbIdeographic }, { 0x3049, 0x3049, LbClosing },
    { 0x304A, 0x3062, LbIdeographic }, { 0x3063, 0x3063, LbClosing }, { 0x3064, 0x3082, LbIdeographic },
    { 0x3083, 0x3083, LbClosing }, { 0x3084, 0x3084, LbIdeographic }, { 0x3085, 0x3085, LbClosing },
    { 0x3086, 0x3086, LbIdeographic }, { 0x3087, 0x3087, LbClosing }, { 0x3088, 0x308D, LbIdeographic },
    { 0x308E, 0x308E, LbClosing }, { 0x308F, 0x3094, LbIdeographic }, { 0x3095, 0x3096, LbClosing },
    { 0x3097, 0x309A, LbIdeographic }, { 0x309B, 0x309E, LbClosing }, { 0x309F, 0x30A0, LbIdeographic },
    { 0x30A1, 0x30A1, LbClosing }, { 0x30A2, 0x30A2, LbIdeographic }, { 0x30A3, 0x30A3, LbClosing },
    { 0x30A4, 0x30A4, LbIdeographic }, { 0x30A5, 0x30A5, LbClosing }, { 0x30A6, 0x30A6, LbIdeographic },
    { 0x30A7, 0x30A7, LbClosing }, { 0x30A8, 0x30A8, LbIdeographic }, { 0x30A9, 0x30A9, LbClosing },
    { 0x30AA, 0x30C2, LbIdeographic }, { 0x30C3, 0x30C3, LbClosing }, { 0x30C4, 0x30E2, LbIdeographic },
    { 0x30E3, 0x30E3, LbClosing }, { 0x30E4, 0x30E4, LbIdeographic }, { 0x30E5, 0x30E5, LbClosing },
    { 0x30E6, 0x30E6, LbIdeographic }, { 0x30E7, 0x30E7, LbClosing }, { 0x30E8, 0x30ED, LbIdeographic },
    { 0x30EE, 0x30EE, LbClosing }, { 0x30EF, 0x30F4, LbIdeographic }, { 0x30F5, 0x30F6, LbClosing },
    { 0x30F7, 0x30FA, LbIdeographic }, { 0x30FB, 0x30FE, LbClosing }, { 0x30FF, 0x31FF, LbIdeographic },
    { 0x3200, 0x4DBF, LbIdeographic }, { 0x4E00, 0x9FFF, LbIdeographic }, { 0xA000, 0xA4CF, LbIdeographic },
    { 0xA960, 0xA97F, LbIdeographic }, { 0xAA60, 0xAADF, LbIdeographic }, { 0xAC00, 0xD7FF, LbIdeographic },
    { 0xF900, 0xFAFF, LbIdeographic }, { 0xFE30, 0xFE4F, LbIdeographic },
    { 0xFF01, 0xFF01, LbClosing }, { 0xFF02, 0xFF07, LbIdeographic }, { 0xFF08, 0xFF08, LbOpening },
    { 0xFF09, 0xFF09, LbClosing }, { 0xFF0A, 0xFF0B, LbIdeographic }, { 0xFF0C, 0xFF0C, LbClosing },
    { 0xFF0D, 0xFF0D, LbIdeographic }, { 0xFF0E, 0xFF0E, LbClosing }, { 0xFF0F, 0xFF19, LbIdeographic },
    { 0xFF1A, 0xFF1B, LbClosing }, { 0xFF1C, 0xFF1E, LbIdeographic }, { 0xFF1F, 0xFF1F, LbClosing },
    { 0xFF20, 0xFF3A, LbIdeographic }, { 0xFF3B, 0xFF3B, LbOpening }, { 0xFF3C, 0xFF3C, LbIdeographic },
    { 0xFF3D, 0xFF3D, LbClosing }, { 0xFF3E, 0xFF5A, LbIdeographic }, { 0xFF5B, 0xFF5B, LbOpening },
    { 0xFF5C, 0xFF5C, LbIdeographic }, { 0xFF5D, 0xFF5D, LbClosing }, { 0xFF5E, 0xFF60, LbIdeographic },
    { 0xFF61, 0xFF61, LbClosing }, { 0xFF62, 0xFF62, LbOpening }, { 0xFF63, 0xFF64, LbClosing },
    { 0xFF65, 0xFFEF, LbIdeographic },
    { 0x16FE0, 0x18AFF, LbIdeographic }, { 0x1B000, 0x1B2FF, LbIdeographic }, { 0x1F000, 0x1FAFF, LbIdeographic },
    { 0x20000, 0x3FFFD, LbIdeographic },
};

static int FallbackClass(unsigned cp) {
    int lo = 0, hi = (int)(sizeof FallbackRanges / sizeof FallbackRanges[0]) - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (cp < FallbackRanges[mid].first) hi = mid - 1;
        else if (cp > FallbackRanges[mid].last) lo = mid + 1;
        else return FallbackRanges[mid].cls;
    }
    return LbOther;
}

// May a line break between a character of class `before` and one of `after`? Next to an ideographic letter, unless
// the next one is closing punctuation or the one before opens; after closing punctuation before an ideographic or
// opening one.
static bool FallbackMayBreak(unsigned before, unsigned after) {
    int a = FallbackClass(before), b = FallbackClass(after);
    if (b == LbClosing || a == LbOpening) return false;
    return a == LbIdeographic || b == LbIdeographic || (a == LbClosing && b == LbOpening);
}
