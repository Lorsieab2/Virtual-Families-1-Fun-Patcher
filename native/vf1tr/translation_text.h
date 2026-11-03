/* translation_text.h -- reading a translation file (format 1), with no C runtime and no
   allocation of its own: the caller hands every buffer in.  The same rules as
   src/translation_format.py (tests/test_translations_runtime.py runs both on the same files):

     * UTF-8 with or without a BOM, or UTF-16 LE / BE with a BOM; anything else: no file;
     * a header row "Key<TAB>English<TAB>Translation" first (comments "#" and blank lines aside);
     * @format (a newer major version: no file), @game (must be this game), @code;
     * rows Key<TAB>English<TAB>Translation[<TAB>Notes...], quoted fields unquoted, \n \t \\;
     * a row is used only if its key is well formed, its hash is the SHA-256 of its English,
       its translation is not empty and keeps the English's placeholders: the same printf
       conversions in the same order, the same {variables}, and well-formed choices
       {%N: key=text | ...} on number conversions.

   Virtual Families 1 (patcher/translation_format.py's docstring): {name}, {name2} and {award} are the
   variables the game fills (GetStringFromNameGenderTemplate 0x44FDD0); {he/she} and {his/2/her} are its
   own person choices, and {name: m=.. | f=..} / {name2: ...} are written out in that form, so the game
   makes the choice with the real person.  A person choice is only allowed in a line the game fills.

   Ported from the Fish and Plant Tycoon Fix Patcher (native/ftfp_translations/translation_text.h).
   Everything is bounded by the buffers given; nothing here can fault on any input. */
#ifndef FTFP_TRANSLATION_TEXT_H
#define FTFP_TRANSLATION_TEXT_H

/* ------------------------------------------------------------------ SHA-256 (the key's hash) */

static const unsigned int TT_K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};

#define TT_ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void tt_sha_block(unsigned int h[8], const unsigned char *p) {
    unsigned int w[64], a, b, c, d, e, f, g, k, t1, t2;
    int i;
    for (i = 0; i < 16; ++i) {
        w[i] = ((unsigned int)p[4 * i] << 24) | ((unsigned int)p[4 * i + 1] << 16) | ((unsigned int)p[4 * i + 2] << 8) | p[4 * i + 3];
    }
    for (i = 16; i < 64; ++i) {
        unsigned int s0 = TT_ROR(w[i - 15], 7) ^ TT_ROR(w[i - 15], 18) ^ (w[i - 15] >> 3);
        unsigned int s1 = TT_ROR(w[i - 2], 17) ^ TT_ROR(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    a = h[0]; b = h[1]; c = h[2]; d = h[3]; e = h[4]; f = h[5]; g = h[6]; k = h[7];
    for (i = 0; i < 64; ++i) {
        t1 = k + (TT_ROR(e, 6) ^ TT_ROR(e, 11) ^ TT_ROR(e, 25)) + ((e & f) ^ (~e & g)) + TT_K[i] + w[i];
        t2 = (TT_ROR(a, 2) ^ TT_ROR(a, 13) ^ TT_ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        k = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += k;
}

/* The first 32 bits of the SHA-256 of data[0..n). */
static unsigned int tt_sha256_head(const unsigned char *data, unsigned int n) {
    unsigned int h[8] = { 0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19 };
    unsigned char block[64];
    unsigned int i, done = 0, left;
    unsigned long long bits = (unsigned long long)n * 8u;
    while (n - done >= 64) {
        tt_sha_block(h, data + done);
        done += 64;
    }
    left = n - done;
    for (i = 0; i < 64; ++i) block[i] = 0;
    for (i = 0; i < left; ++i) block[i] = data[done + i];
    block[left] = 0x80;
    if (left >= 56) {
        tt_sha_block(h, block);
        for (i = 0; i < 64; ++i) block[i] = 0;
    }
    for (i = 0; i < 8; ++i) block[63 - i] = (unsigned char)(bits >> (8 * i));
    tt_sha_block(h, block);
    return h[0];
}

/* ------------------------------------------------------------------ small text helpers */

static int tt_is_space(unsigned char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v'; }
static int tt_is_digit(unsigned char c) { return c >= '0' && c <= '9'; }
static int tt_is_alpha(unsigned char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
static int tt_lower(int c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }

/* A span of text: [s, s + n). */
typedef struct tt_span { const char *s; int n; } tt_span;

static tt_span tt_strip(tt_span t) {
    while (t.n > 0 && tt_is_space((unsigned char)t.s[0])) { ++t.s; --t.n; }
    while (t.n > 0 && tt_is_space((unsigned char)t.s[t.n - 1])) --t.n;
    return t;
}

static int tt_span_is(tt_span t, const char *word) {
    int i;
    for (i = 0; i < t.n; ++i) if (word[i] == 0 || tt_lower((unsigned char)t.s[i]) != tt_lower((unsigned char)word[i])) return 0;
    return word[t.n] == 0;
}

static int tt_span_eq(tt_span a, tt_span b) {
    int i;
    if (a.n != b.n) return 0;
    for (i = 0; i < a.n; ++i) if (a.s[i] != b.s[i]) return 0;
    return 1;
}

/* ------------------------------------------------------------------ decoding the file */

/* The file's bytes as UTF-8 in out[0..cap); returns its length, or -1 when the file is not
   UTF-8 or UTF-16 with a BOM.  A UTF-8 BOM is dropped. */
static int tt_decode(const unsigned char *in, int n, char *out, int cap) {
    int i = 0, o = 0;
    if (n >= 2 && ((in[0] == 0xFF && in[1] == 0xFE) || (in[0] == 0xFE && in[1] == 0xFF))) {
        int be = in[0] == 0xFE;
        for (i = 2; i + 1 < n; i += 2) {
            unsigned int u = be ? ((unsigned int)in[i] << 8) | in[i + 1] : ((unsigned int)in[i + 1] << 8) | in[i];
            if (u >= 0xD800 && u <= 0xDBFF) {
                unsigned int lo;
                if (i + 3 >= n) return -1;
                lo = be ? ((unsigned int)in[i + 2] << 8) | in[i + 3] : ((unsigned int)in[i + 3] << 8) | in[i + 2];
                if (lo < 0xDC00 || lo > 0xDFFF) return -1;
                u = 0x10000 + ((u - 0xD800) << 10) + (lo - 0xDC00);
                i += 2;
            } else if (u >= 0xDC00 && u <= 0xDFFF) {
                return -1;
            }
            if (o + 4 >= cap) return -1;
            if (u < 0x80) out[o++] = (char)u;
            else if (u < 0x800) { out[o++] = (char)(0xC0 | (u >> 6)); out[o++] = (char)(0x80 | (u & 0x3F)); }
            else if (u < 0x10000) {
                out[o++] = (char)(0xE0 | (u >> 12)); out[o++] = (char)(0x80 | ((u >> 6) & 0x3F)); out[o++] = (char)(0x80 | (u & 0x3F));
            } else {
                out[o++] = (char)(0xF0 | (u >> 18)); out[o++] = (char)(0x80 | ((u >> 12) & 0x3F));
                out[o++] = (char)(0x80 | ((u >> 6) & 0x3F)); out[o++] = (char)(0x80 | (u & 0x3F));
            }
        }
        if (i != n) return -1;                  /* an odd byte at the end */
        return o;
    }
    if (n >= 3 && in[0] == 0xEF && in[1] == 0xBB && in[2] == 0xBF) i = 3;
    while (i < n) {                             /* validate UTF-8 as Python's strict decoder does */
        unsigned char c = in[i];
        int extra, k;
        unsigned int u;
        if (c < 0x80) { extra = 0; u = c; }
        else if (c >= 0xC2 && c <= 0xDF) { extra = 1; u = c & 0x1F; }
        else if (c >= 0xE0 && c <= 0xEF) { extra = 2; u = c & 0x0F; }
        else if (c >= 0xF0 && c <= 0xF4) { extra = 3; u = c & 0x07; }
        else return -1;
        for (k = 1; k <= extra; ++k) {
            if (i + k >= n || (in[i + k] & 0xC0) != 0x80) return -1;
            u = (u << 6) | (in[i + k] & 0x3F);
        }
        if ((extra == 2 && (u < 0x800 || (u >= 0xD800 && u <= 0xDFFF))) || (extra == 3 && (u < 0x10000 || u > 0x10FFFF))) return -1;
        if (o + extra + 1 >= cap) return -1;
        for (k = 0; k <= extra; ++k) out[o++] = (char)in[i + k];
        i += extra + 1;
    }
    return o;
}

/* The next code point of UTF-8 text at *at (already validated); moves *at on. */
static unsigned int tt_next_cp(const char *s, int n, int *at) {
    const unsigned char *p = (const unsigned char *)s;
    int i = *at;
    unsigned int c = p[i];
    if (c < 0x80 || i + 1 >= n) { *at = i + 1; return c; }
    if (c < 0xE0) { *at = i + 2; return ((c & 0x1F) << 6) | (p[i + 1] & 0x3F); }
    if (c < 0xF0 || i + 3 >= n) {
        if (i + 2 >= n) { *at = n; return 0xFFFD; }
        *at = i + 3;
        return ((c & 0x0F) << 12) | ((p[i + 1] & 0x3F) << 6) | (p[i + 2] & 0x3F);
    }
    *at = i + 4;
    return ((c & 0x07) << 18) | ((p[i + 1] & 0x3F) << 12) | ((p[i + 2] & 0x3F) << 6) | (p[i + 3] & 0x3F);
}

/* ------------------------------------------------------------------ placeholders */

#define TT_MAX_CONV 16
#define TT_MAX_VARS 16
#define TT_MAX_SELECTS 16
#define TT_MAX_BRANCHES 12

typedef struct tt_conv { char type; char length[4]; int stars; int number; int space; const char *s; int n; } tt_conv;

typedef struct tt_branch { tt_span key; tt_span text; } tt_branch;

typedef struct tt_select {
    tt_span subject;
    int start, end;                 /* the select's text: [start, end) */
    int person;                     /* keys m / f / o */
    int native;                     /* the game's own {a/b} (1) or {a/2/b} (2) */
    int nbranches;
    tt_branch branch[TT_MAX_BRANCHES];
} tt_select;

typedef struct tt_template {
    int nconv, nvars, nselects;
    tt_conv conv[TT_MAX_CONV];
    tt_span vars[TT_MAX_VARS];
    tt_select select[TT_MAX_SELECTS];
    int lone_percent;               /* a '%' that is no placeholder: plain text */
    int pct2;                       /* a "%%" token */
    int errors;
} tt_template;

/* A printf conversion at s[i] ('%'); its length, or 0 when it is none (a lone '%'). */
static int tt_conversion(const char *s, int n, int i, tt_conv *out) {
    int j = i + 1, stars = 0, l = 0, space = 0;
    while (j < n && (s[j] == '-' || s[j] == '+' || s[j] == ' ' || s[j] == '#' || s[j] == '0')) { if (s[j] == ' ') space = 1; ++j; }
    if (j < n && s[j] == '*') { ++stars; ++j; }
    else while (j < n && tt_is_digit((unsigned char)s[j])) ++j;
    if (j < n && s[j] == '.') {
        if (j + 1 < n && s[j + 1] == '*') { ++stars; j += 2; }
        else if (j + 1 < n && tt_is_digit((unsigned char)s[j + 1])) { j += 1; while (j < n && tt_is_digit((unsigned char)s[j])) ++j; }
        else return 0;
    }
    out->length[0] = out->length[1] = out->length[2] = out->length[3] = 0;
    if (j + 1 < n && s[j] == 'h' && s[j + 1] == 'h') { out->length[0] = 'h'; out->length[1] = 'h'; l = 2; }
    else if (j < n && s[j] == 'h') { out->length[0] = 'h'; l = 1; }
    else if (j + 1 < n && s[j] == 'l' && s[j + 1] == 'l') { out->length[0] = 'l'; out->length[1] = 'l'; l = 2; }
    else if (j < n && s[j] == 'l') { out->length[0] = 'l'; l = 1; }
    else if (j < n && s[j] == 'L') { out->length[0] = 'L'; l = 1; }
    else if (j + 2 < n && s[j] == 'I' && s[j + 1] == '6' && s[j + 2] == '4') { out->length[0] = 'I'; out->length[1] = '6'; out->length[2] = '4'; l = 3; }
    else if (j + 2 < n && s[j] == 'I' && s[j + 1] == '3' && s[j + 2] == '2') { out->length[0] = 'I'; out->length[1] = '3'; out->length[2] = '2'; l = 3; }
    else if (j < n && s[j] == 'I') { out->length[0] = 'I'; l = 1; }
    else if (j < n && s[j] == 'w') { out->length[0] = 'w'; l = 1; }
    j += l;
    if (j >= n) return 0;
    {
        const char *types = "diouxXcCsSfFeEgGaApn";
        int k;
        for (k = 0; types[k]; ++k) {
            if (s[j] == types[k]) {
                out->type = s[j] == 'i' ? 'd' : s[j];
                out->stars = stars;
                out->space = space;
                out->s = s + i;
                out->n = j + 1 - i;
                out->number = s[j] == 'd' || s[j] == 'i' || s[j] == 'o' || s[j] == 'u' || s[j] == 'x' || s[j] == 'X';
                return j + 1 - i;
            }
        }
    }
    return 0;
}

static int tt_conv_same(const tt_conv *a, const tt_conv *b) {
    return a->type == b->type && a->stars == b->stars && a->length[0] == b->length[0] && a->length[1] == b->length[1]
        && a->length[2] == b->length[2];
}

/* A placeholder of a translation at s[i] ('%'), judged by its English `src` (translation_format.Source.token_at):
   "%%" when the English has one (2, conv->n = 0), one of the English's conversions -- the same text, or the same
   kind of value with another width or precision but never by the space flag alone -- (its length), or 0: a plain
   '%'.  A line that is no printf format has no placeholders (tt_translation_ok), so all its '%' are plain. */
static int tt_source_token(const tt_template *src, const char *s, int n, int i, tt_conv *conv) {
    int len, k, j;
    conv->n = 0;
    if (src->pct2 && i + 1 < n && s[i + 1] == '%') return 2;
    len = tt_conversion(s, n, i, conv);
    if (len == 0) return 0;
    for (k = 0; k < src->nconv; ++k) {
        if (src->conv[k].n != len) continue;
        for (j = 0; j < len && src->conv[k].s[j] == s[i + j]; ++j) {}
        if (j == len) return len;
    }
    if (!conv->space) for (k = 0; k < src->nconv; ++k) if (tt_conv_same(&src->conv[k], conv)) return len;
    return 0;
}

/* The text handed to printf for a FORMAT line: every '%' that is no placeholder of the English `src` written as
   "%%" (translation_format.runtime_text).  Returns the length written to out (cap bytes), or -1. */
static int tt_escape_percent(const char *s, int n, const tt_template *src, char *out, int cap) {
    int i = 0, o = 0;
    while (i < n) {
        if (s[i] == '%') {
            tt_conv conv;
            int len = tt_source_token(src, s, n, i, &conv), k;
            if (len == 0) {
                if (o + 2 >= cap) return -1;
                out[o++] = '%';
                out[o++] = '%';
                ++i;
                continue;
            }
            if (o + len >= cap) return -1;
            for (k = 0; k < len; ++k) out[o++] = s[i + k];
            i += len;
            continue;
        }
        if (o + 1 >= cap) return -1;
        out[o++] = s[i++];
    }
    out[o] = 0;
    return o;
}

static int tt_is_name(tt_span t) {
    int i;
    if (t.n <= 0 || !(tt_is_alpha((unsigned char)t.s[0]) || t.s[0] == '_')) return 0;
    for (i = 1; i < t.n; ++i) {
        unsigned char c = (unsigned char)t.s[i];
        if (!(tt_is_alpha(c) || tt_is_digit(c) || c == '_')) return 0;
    }
    return 1;
}

static void tt_add_var(tt_template *t, tt_span name) {
    int k;
    for (k = 0; k < t->nvars; ++k) if (tt_span_eq(t->vars[k], name)) return;
    if (t->nvars < TT_MAX_VARS) t->vars[t->nvars++] = name; else t->errors++;
}

static int tt_find(const char *s, int n, int from, char c) {
    int i;
    for (i = from; i < n; ++i) if (s[i] == c) return i;
    return -1;
}

static int tt_is_number_key(tt_span k) {
    int i;
    if (k.n >= 2 && k.s[0] == '=') {
        for (i = 1; i < k.n; ++i) if (!tt_is_digit((unsigned char)k.s[i])) return 0;
        return 1;
    }
    return tt_span_is(k, "zero") || tt_span_is(k, "one") || tt_span_is(k, "two") || tt_span_is(k, "few")
        || tt_span_is(k, "many") || tt_span_is(k, "other");
}

static int tt_exact_case(tt_span k, const char *word) {
    int i;
    for (i = 0; i < k.n; ++i) if (word[i] == 0 || k.s[i] != word[i]) return 0;
    return word[k.n] == 0;
}

static int tt_is_person_key(tt_span k) { return tt_exact_case(k, "m") || tt_exact_case(k, "f") || tt_exact_case(k, "o"); }

static int tt_is_plural_key(tt_span k) {
    return tt_exact_case(k, "zero") || tt_exact_case(k, "one") || tt_exact_case(k, "two") || tt_exact_case(k, "few")
        || tt_exact_case(k, "many") || tt_exact_case(k, "other") || (k.n >= 2 && k.s[0] == '=' && tt_is_number_key(k));
}

/* One branch "key=text" (BRANCH_RE: ^(=\d+|[A-Za-z]+)\s*=(.*)$ on the stripped branch). */
static int tt_branch_parse(tt_span raw, tt_branch *out) {
    tt_span b = tt_strip(raw);
    int i = 0;
    if (b.n == 0) return 0;
    if (b.s[0] == '=') {
        i = 1;
        while (i < b.n && tt_is_digit((unsigned char)b.s[i])) ++i;
        if (i == 1) return 0;
    } else {
        while (i < b.n && tt_is_alpha((unsigned char)b.s[i])) ++i;
        if (i == 0) return 0;
    }
    out->key.s = b.s;
    out->key.n = i;
    while (i < b.n && tt_is_space((unsigned char)b.s[i])) ++i;
    if (i >= b.n || b.s[i] != '=') return 0;
    out->text.s = b.s + i + 1;
    out->text.n = b.n - i - 1;
    out->text = tt_strip(out->text);
    return 1;
}

/* A select's body from s[i] (after ':') to its '}'; returns the index after it. */
static int tt_select_body(const char *s, int n, int i, tt_template *t, tt_select *sel, const tt_template *src) {
    int start = i, closed = 0, k, person = 1, number = 1;
    tt_span raws[TT_MAX_BRANCHES + 1];
    int nraw = 0;
    while (i < n) {
        char c = s[i];
        if (i + 1 < n && ((c == '{' && s[i + 1] == '{') || (c == '}' && s[i + 1] == '}'))) { i += 2; continue; }
        if (c == '\\' && i + 1 < n && s[i + 1] == '|') { i += 2; continue; }
        if (c == '|' || c == '}') {
            if (nraw <= TT_MAX_BRANCHES) { raws[nraw].s = s + start; raws[nraw].n = i - start; ++nraw; }
            else t->errors++;
            start = i + 1;
            ++i;
            if (c == '}') { closed = 1; break; }
            continue;
        }
        if (c == '{') {
            int end = tt_find(s, n, i + 1, '}');
            tt_span inner;
            if (end == -1) { t->errors++; return n; }
            inner.s = s + i + 1;
            inner.n = end - i - 1;
            if (tt_find(inner.s, inner.n, 0, ':') != -1) { t->errors++; return n; }
            if (!tt_is_name(tt_strip(inner))) t->errors++; else tt_add_var(t, tt_strip(inner));
            i = end + 1;
            continue;
        }
        if (c == '%' && src != 0) {
            tt_conv conv;
            int len = tt_source_token(src, s, n, i, &conv);
            if (len == 0) { t->lone_percent = 1; ++i; continue; }
            if (conv.n > 0) t->errors++;                                   /* a placeholder inside a choice */
            i += len;
            continue;
        }
        if (c == '%') {
            tt_conv conv;
            int len;
            if (i + 1 < n && s[i + 1] == '%') { i += 2; continue; }
            len = tt_conversion(s, n, i, &conv);
            if (len > 0) { t->errors++; i += len; continue; }
        }
        ++i;
    }
    if (!closed) t->errors++;
    sel->nbranches = 0;
    for (k = 0; k < nraw; ++k) {
        tt_branch b;
        int j;
        if (!tt_branch_parse(raws[k], &b)) { t->errors++; continue; }
        for (j = 0; j < sel->nbranches; ++j) if (tt_span_eq(sel->branch[j].key, b.key)) t->errors++;
        if (sel->nbranches < TT_MAX_BRANCHES) sel->branch[sel->nbranches++] = b; else t->errors++;
    }
    if (sel->nbranches == 0 && closed) t->errors++;
    for (k = 0; k < sel->nbranches; ++k) {
        if (!tt_is_person_key(sel->branch[k].key)) person = 0;
        if (!tt_is_plural_key(sel->branch[k].key)) number = 0;
    }
    if (sel->nbranches > 0 && !person && !number) t->errors++;
    sel->person = person && sel->nbranches > 0;
    sel->end = i;
    return i;
}

static const char TT_M[] = "m", TT_F[] = "f", TT_NAME[] = "name", TT_NAME2[] = "name2";

/* The game's person choice s[open..close] = "{a/b}" or "{a/2/b}" (no '|', '\\', '{' in it): a person select. */
static int tt_native_choice(const char *s, int open, int close, tt_template *t) {
    int i, slash = -1, second = 0, end_a, start_b;
    tt_select *sel;
    for (i = open + 1; i < close; ++i) {
        char c = s[i];
        if (c == '{' || c == '|' || c == '\\') return 0;
        if (c == '/') {
            if (slash != -1) {
                if (second || i != slash + 2 || s[slash + 1] != '2') return 0;
                second = 1;
            } else {
                slash = i;
            }
        }
    }
    if (slash == -1) return 0;
    if (t->nselects >= TT_MAX_SELECTS) { t->errors++; return 1; }
    end_a = slash;
    start_b = second ? slash + 3 : slash + 1;
    sel = &t->select[t->nselects++];
    sel->subject.s = second ? TT_NAME2 : TT_NAME;
    sel->subject.n = second ? 5 : 4;
    sel->start = open;
    sel->end = close + 1;
    sel->person = 1;
    sel->native = second ? 2 : 1;
    sel->nbranches = 2;
    sel->branch[0].key.s = TT_M; sel->branch[0].key.n = 1;
    sel->branch[0].text.s = s + open + 1; sel->branch[0].text.n = end_a - open - 1;
    sel->branch[1].key.s = TT_F; sel->branch[1].key.n = 1;
    sel->branch[1].text.s = s + start_b; sel->branch[1].text.n = close - start_b;
    return 1;
}

/* `src`: a translation's English (only its placeholders count; any other '%' is plain text), or 0 for an English. */
static void tt_parse_template(const char *s, int n, tt_template *t, const tt_template *src) {
    int i = 0;
    t->nconv = t->nvars = t->nselects = t->lone_percent = t->pct2 = t->errors = 0;
    while (i < n) {
        char c = s[i];
        if (i + 1 < n && ((c == '{' && s[i + 1] == '{') || (c == '}' && s[i + 1] == '}'))) { i += 2; continue; }
        if (c == '%' && src != 0) {
            tt_conv conv;
            int len = tt_source_token(src, s, n, i, &conv);
            if (len == 0) { t->lone_percent = 1; ++i; continue; }
            if (conv.n == 0) { t->pct2 = 1; i += 2; continue; }
            if (conv.type == 'n') t->errors++;
            if (t->nconv < TT_MAX_CONV) t->conv[t->nconv++] = conv; else t->errors++;
            i += len;
            continue;
        }
        if (c == '%') {
            tt_conv conv;
            int len;
            if (i + 1 < n && s[i + 1] == '%') { t->pct2 = 1; i += 2; continue; }
            len = tt_conversion(s, n, i, &conv);
            if (len > 0) {
                if (conv.type == 'n') t->errors++;
                if (t->nconv < TT_MAX_CONV) t->conv[t->nconv++] = conv; else t->errors++;
                i += len;
                continue;
            }
            t->lone_percent = 1;
            ++i;
            continue;
        }
        if (c == '{') {
            int colon = tt_find(s, n, i + 1, ':'), close = tt_find(s, n, i + 1, '}');
            if (close == -1 && colon == -1) { t->errors++; return; }
            if (close != -1 && (colon == -1 || close < colon)) {
                tt_span name;
                name.s = s + i + 1;
                name.n = close - i - 1;
                if (tt_is_name(tt_strip(name))) tt_add_var(t, tt_strip(name));
                else if (!tt_native_choice(s, i, close, t)) t->errors++;
                i = close + 1;
                continue;
            }
            {
                tt_select dummy, *sel = t->nselects < TT_MAX_SELECTS ? &t->select[t->nselects] : &dummy;
                if (t->nselects >= TT_MAX_SELECTS) t->errors++;
                sel->subject.s = s + i + 1;
                sel->subject.n = colon - i - 1;
                sel->subject = tt_strip(sel->subject);
                if (sel->subject.n == 0) t->errors++;
                sel->start = i;
                sel->native = 0;
                i = tt_select_body(s, n, colon + 1, t, sel, src);
                if (sel != &dummy) t->nselects++;
            }
            continue;
        }
        if (c == '}') { t->errors++; ++i; continue; }
        ++i;
    }
}

/* 1 when the translation keeps the English's placeholders (the row may be used).  `is_format`: the program uses
   the line as a printf format; any other line has no placeholders (every '%' in it is plain text). */
static int tt_translation_ok(const char *eng, int en, const char *tra, int tn, tt_template *te, tt_template *tt,
                             int is_format) {
    int k, j;
    tt_parse_template(eng, en, te, 0);
    if (!is_format) te->nconv = te->pct2 = 0;
    tt_parse_template(tra, tn, tt, te);
    if (tt->errors) return 0;
    if (te->nconv != tt->nconv) return 0;
    for (k = 0; k < te->nconv; ++k) if (!tt_conv_same(&te->conv[k], &tt->conv[k])) return 0;
    for (k = 0; k < te->nvars; ++k) {
        int found = 0;
        for (j = 0; j < tt->nvars; ++j) if (tt_span_eq(te->vars[k], tt->vars[j])) found = 1;
        if (!found) return 0;
    }
    for (k = 0; k < tt->nvars; ++k) {
        int found = 0;
        for (j = 0; j < te->nvars; ++j) if (tt_span_eq(tt->vars[k], te->vars[j])) found = 1;
        if (!found) return 0;
    }
    for (k = 0; k < tt->nselects; ++k) {
        const tt_select *sel = &tt->select[k];
        int index = 0, i;
        if (tt_exact_case(sel->subject, "name") || tt_exact_case(sel->subject, "name2")) {
            int b, m = 0;
            if (!sel->person) return 0;                                    /* a person: m / f / o */
            if (te->nvars == 0 && te->nselects == 0) return 0;             /* a line the game does not fill */
            for (b = 0; b < sel->nbranches; ++b) {
                const tt_span *x = &sel->branch[b].text;
                if (tt_exact_case(sel->branch[b].key, "m") || tt_exact_case(sel->branch[b].key, "f")) m = 1;
                for (i = 0; i < x->n; ++i) if (x->s[i] == '/' || x->s[i] == '{' || x->s[i] == '}') return 0;
            }
            if (!m) return 0;
            continue;
        }
        if (tt_exact_case(sel->subject, "award")) {
            if (sel->person && sel->nbranches > 0) return 0;              /* a number needs number keys */
            continue;
        }
        if (sel->subject.n < 2 || sel->subject.s[0] != '%') return 0;      /* no other named subjects */
        for (i = 1; i < sel->subject.n; ++i) {
            if (!tt_is_digit((unsigned char)sel->subject.s[i]) || index > 1000) return 0;
            index = index * 10 + (sel->subject.s[i] - '0');
        }
        if (index < 1 || index > te->nconv) return 0;
        if (!te->conv[index - 1].number) return 0;                         /* a text: no choices */
        if (sel->person && sel->nbranches > 0) return 0;                   /* a number needs number keys */
    }
    return 1;
}

/* ------------------------------------------------------------------ plural rules (CLDR) */

/* The same table as translation_format.PLURAL_RULES. */
enum { TT_EN, TT_FR, TT_ES, TT_PT, TT_RU, TT_PL, TT_CS, TT_HR, TT_SL, TT_LT, TT_LV, TT_RO, TT_AR, TT_HE,
       TT_GA, TT_CY, TT_NONE, TT_ZERO_ONE, TT_IS, TT_FIL };

typedef struct tt_lang { const char *code; int rule; } tt_lang;

static const tt_lang TT_LANGS[] = {
    { "en", TT_EN }, { "fr", TT_FR }, { "es", TT_ES }, { "it", TT_ES }, { "ca", TT_ES }, { "pt", TT_PT },
    { "pt-pt", TT_ES }, { "ru", TT_RU }, { "uk", TT_RU }, { "be", TT_RU }, { "pl", TT_PL }, { "cs", TT_CS },
    { "sk", TT_CS }, { "hr", TT_HR }, { "sr", TT_HR }, { "bs", TT_HR }, { "sl", TT_SL }, { "lt", TT_LT },
    { "lv", TT_LV }, { "ro", TT_RO }, { "mo", TT_RO }, { "ar", TT_AR }, { "he", TT_HE }, { "iw", TT_HE },
    { "ga", TT_GA }, { "cy", TT_CY }, { "ja", TT_NONE }, { "zh", TT_NONE }, { "ko", TT_NONE }, { "vi", TT_NONE },
    { "th", TT_NONE }, { "id", TT_NONE }, { "ms", TT_NONE }, { "km", TT_NONE }, { "lo", TT_NONE },
    { "my", TT_NONE }, { "hi", TT_ZERO_ONE }, { "bn", TT_ZERO_ONE }, { "am", TT_ZERO_ONE }, { "fa", TT_ZERO_ONE },
    { "gu", TT_ZERO_ONE }, { "kn", TT_ZERO_ONE }, { "mr", TT_ZERO_ONE }, { "zu", TT_ZERO_ONE }, { "is", TT_IS },
    { "mk", TT_IS }, { "fil", TT_FIL }, { "tl", TT_FIL },
};

static int tt_code_is(tt_span code, const char *name, int whole) {
    int i;
    for (i = 0; name[i]; ++i) {
        if (i >= code.n) return 0;
        {
            int c = tt_lower((unsigned char)code.s[i]);
            if (c == '_') c = '-';
            if (c != name[i]) return 0;
        }
    }
    return whole ? i == code.n : (i == code.n || code.s[i] == '-' || code.s[i] == '_');
}

static int tt_rule_for(tt_span code) {
    int k;
    code = tt_strip(code);
    for (k = 0; k < (int)(sizeof TT_LANGS / sizeof TT_LANGS[0]); ++k) if (tt_code_is(code, TT_LANGS[k].code, 1)) return TT_LANGS[k].rule;
    for (k = 0; k < (int)(sizeof TT_LANGS / sizeof TT_LANGS[0]); ++k) if (tt_code_is(code, TT_LANGS[k].code, 0)) return TT_LANGS[k].rule;
    return TT_EN;
}

/* "zero" "one" "two" "few" "many" "other" for a whole number. */
static const char *tt_plural(int rule, unsigned int n) {
    unsigned int m10 = n % 10, m100 = n % 100;
    int million = n != 0 && n % 1000000 == 0;
    switch (rule) {
    case TT_FR: return n <= 1 ? "one" : million ? "many" : "other";
    case TT_ES: return n == 1 ? "one" : million ? "many" : "other";
    case TT_PT: return n <= 1 ? "one" : million ? "many" : "other";
    case TT_RU: return m10 == 1 && m100 != 11 ? "one" : (m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14)) ? "few" : "many";
    case TT_PL: return n == 1 ? "one" : (m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14)) ? "few" : "many";
    case TT_CS: return n == 1 ? "one" : (n >= 2 && n <= 4) ? "few" : "other";
    case TT_HR: return m10 == 1 && m100 != 11 ? "one" : (m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14)) ? "few" : "other";
    case TT_SL: return m100 == 1 ? "one" : m100 == 2 ? "two" : (m100 == 3 || m100 == 4) ? "few" : "other";
    case TT_LT: return (m10 == 1 && !(m100 >= 11 && m100 <= 19)) ? "one" : (m10 >= 2 && !(m100 >= 11 && m100 <= 19)) ? "few" : "other";
    case TT_LV: return (m10 == 0 || (m100 >= 11 && m100 <= 19)) ? "zero" : (m10 == 1 && m100 != 11) ? "one" : "other";
    case TT_RO: return n == 1 ? "one" : (n == 0 || (m100 >= 1 && m100 <= 19)) ? "few" : "other";
    case TT_AR: return n == 0 ? "zero" : n == 1 ? "one" : n == 2 ? "two" : (m100 >= 3 && m100 <= 10) ? "few" : (m100 >= 11) ? "many" : "other";
    case TT_HE: return n == 1 ? "one" : n == 2 ? "two" : "other";
    case TT_GA: return n == 1 ? "one" : n == 2 ? "two" : (n >= 3 && n <= 6) ? "few" : (n >= 7 && n <= 10) ? "many" : "other";
    case TT_CY: return n == 0 ? "zero" : n == 1 ? "one" : n == 2 ? "two" : n == 3 ? "few" : n == 6 ? "many" : "other";
    case TT_NONE: return "other";
    case TT_ZERO_ONE: return n <= 1 ? "one" : "other";
    case TT_IS: return m10 == 1 && m100 != 11 ? "one" : "other";
    case TT_FIL: return (n >= 1 && n <= 3) || (m10 != 4 && m10 != 6 && m10 != 9) ? "one" : "other";
    default: return n == 1 ? "one" : "other";
    }
}

/* ------------------------------------------------------------------ choosing and writing out */

/* The branch a select takes: its number `value` when `known`, else o / other. */
static const tt_branch *tt_choose(const tt_select *sel, int rule, int known, int value) {
    int k;
    const tt_branch *other = 0;
    if (sel->nbranches == 0) return 0;
    if (sel->person) {
        for (k = 0; k < sel->nbranches; ++k) if (tt_exact_case(sel->branch[k].key, "o")) return &sel->branch[k];
        return &sel->branch[0];
    }
    for (k = 0; k < sel->nbranches; ++k) if (tt_exact_case(sel->branch[k].key, "other")) other = &sel->branch[k];
    if (known) {
        unsigned int n = value < 0 ? (unsigned int)(-(value + 1)) + 1u : (unsigned int)value;
        const char *category = tt_plural(rule, n);
        for (k = 0; k < sel->nbranches; ++k) {
            const tt_span *key = &sel->branch[k].key;
            if (key->n >= 2 && key->s[0] == '=') {
                unsigned int v = 0;
                int i;
                for (i = 1; i < key->n && v < 100000000u; ++i) v = v * 10u + (unsigned int)(key->s[i] - '0');
                if (i == key->n && v == n) return &sel->branch[k];
            }
        }
        for (k = 0; k < sel->nbranches; ++k) if (tt_exact_case(sel->branch[k].key, category)) return &sel->branch[k];
    }
    return other != 0 ? other : &sel->branch[0];
}

/* A UTF-8 writer that converts to the game's text: 0 = Windows-1252 (unknown letters '?'),
   1 = UTF-8 as it is, 2 = UTF-16 (wide). `longest` measures instead of writing branches. */
typedef struct tt_out {
    char *buf;
    int cap;                /* in units: bytes, or UTF-16 code units for wide */
    int at;
    int mode;
    int overflow;
} tt_out;

static const unsigned short TT_CP1252[32] = {
    0x20AC, 0, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6, 0x2030, 0x0160, 0x2039, 0x0152, 0, 0x017D, 0,
    0, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122, 0x0161, 0x203A, 0x0153, 0, 0x017E, 0x0178,
};

static void tt_put_unit(tt_out *o, unsigned int u) {
    if (o->mode == 2) {
        if (o->at + 1 >= o->cap) { o->overflow = 1; return; }
        ((unsigned short *)o->buf)[o->at++] = (unsigned short)u;
    } else {
        if (o->at + 1 >= o->cap) { o->overflow = 1; return; }
        o->buf[o->at++] = (char)u;
    }
}

static void tt_put_cp(tt_out *o, unsigned int cp) {
    if (o->mode == 2) {
        if (cp >= 0x10000) {
            cp -= 0x10000;
            tt_put_unit(o, 0xD800 + (cp >> 10));
            tt_put_unit(o, 0xDC00 + (cp & 0x3FF));
        } else {
            tt_put_unit(o, cp);
        }
    } else if (o->mode == 1) {
        if (cp < 0x80) tt_put_unit(o, cp);
        else if (cp < 0x800) { tt_put_unit(o, 0xC0 | (cp >> 6)); tt_put_unit(o, 0x80 | (cp & 0x3F)); }
        else if (cp < 0x10000) { tt_put_unit(o, 0xE0 | (cp >> 12)); tt_put_unit(o, 0x80 | ((cp >> 6) & 0x3F)); tt_put_unit(o, 0x80 | (cp & 0x3F)); }
        else {
            tt_put_unit(o, 0xF0 | (cp >> 18)); tt_put_unit(o, 0x80 | ((cp >> 12) & 0x3F));
            tt_put_unit(o, 0x80 | ((cp >> 6) & 0x3F)); tt_put_unit(o, 0x80 | (cp & 0x3F));
        }
    } else {
        int k;
        if (cp < 0x80 || (cp >= 0xA0 && cp <= 0xFF)) { tt_put_unit(o, cp); return; }
        for (k = 0; k < 32; ++k) if (TT_CP1252[k] != 0 && TT_CP1252[k] == cp) { tt_put_unit(o, 0x80 + (unsigned int)k); return; }
        tt_put_unit(o, '?');
    }
}

/* Writes t[0..n) with {{ }} made single and, inside a branch, \| made |. */
static void tt_put_text(tt_out *o, const char *t, int n, int branch) {
    int i = 0;
    while (i < n) {
        if (i + 1 < n && ((t[i] == '{' && t[i + 1] == '{') || (t[i] == '}' && t[i + 1] == '}'))) { tt_put_cp(o, (unsigned char)t[i]); i += 2; continue; }
        if (branch && t[i] == '\\' && i + 1 < n && t[i + 1] == '|') { tt_put_cp(o, '|'); i += 2; continue; }
        tt_put_cp(o, tt_next_cp(t, n, &i));
    }
}

/* The translation with its choices made: values[k] is the (k+1)-th conversion's number when
   nvalues > k, else every choice takes o / other.  `longest` takes each choice's longest branch
   (to measure).  Returns the units written (without the terminator), or -1 if it did not fit. */
/* A person choice's branch for key "m" or "f" (else o, else the first). */
static const tt_branch *tt_person(const tt_select *sel, const char *key) {
    int k;
    for (k = 0; k < sel->nbranches; ++k) if (tt_exact_case(sel->branch[k].key, key)) return &sel->branch[k];
    for (k = 0; k < sel->nbranches; ++k) if (tt_exact_case(sel->branch[k].key, "o")) return &sel->branch[k];
    return sel->nbranches > 0 ? &sel->branch[0] : 0;
}

static int tt_render(const char *s, int n, const tt_template *t, int rule, const int *values, int nvalues,
                     int longest, tt_out *o) {
    int i = 0, k;
    o->at = 0;
    o->overflow = 0;
    for (k = 0; k < t->nselects; ++k) {
        const tt_select *sel = &t->select[k];
        const tt_branch *b = 0;
        tt_put_text(o, s + i, sel->start - i, 0);
        if (!longest && sel->person && (tt_exact_case(sel->subject, "name") || tt_exact_case(sel->subject, "name2"))) {
            /* the game's own form: it chooses with the real person */
            const tt_branch *m = tt_person(sel, "m"), *f = tt_person(sel, "f");
            tt_put_cp(o, '{');
            if (m != 0) tt_put_text(o, m->text.s, m->text.n, sel->native ? 0 : 1);
            tt_put_cp(o, '/');
            if (tt_exact_case(sel->subject, "name2")) { tt_put_cp(o, '2'); tt_put_cp(o, '/'); }
            if (f != 0) tt_put_text(o, f->text.s, f->text.n, sel->native ? 0 : 1);
            tt_put_cp(o, '}');
            i = sel->end;
            continue;
        }
        if (longest) {
            int j, best = -1;
            for (j = 0; j < sel->nbranches; ++j) {
                tt_out m = *o;
                int before = o->at;
                m.overflow = 0;
                tt_put_text(&m, sel->branch[j].text.s, sel->branch[j].text.n, 1);
                if (m.at - before > best) { best = m.at - before; b = &sel->branch[j]; }
            }
        } else {
            int index = 0, q;
            if (sel->subject.n > 1 && sel->subject.s[0] == '%')
                for (q = 1; q < sel->subject.n && index < 1000; ++q) index = index * 10 + (sel->subject.s[q] - '0');
            b = tt_choose(sel, rule, index >= 1 && index <= nvalues, index >= 1 && index <= nvalues ? values[index - 1] : 0);
        }
        if (b != 0) tt_put_text(o, b->text.s, b->text.n, 1);
        i = sel->end;
    }
    tt_put_text(o, s + i, n - i, 0);
    if (o->overflow) return -1;
    if (o->mode == 2) ((unsigned short *)o->buf)[o->at] = 0; else o->buf[o->at] = 0;
    return o->at;
}

#endif /* FTFP_TRANSLATION_TEXT_H */
