/* vf1tr.dll -- Translations: the player's chosen translation in Virtual Families 1.

   WHAT.  vf1fun.dll loads this DLL last at game start (only while the Translations setting is on) and calls
   VF1Tr_Startup().  It reads the translation the patcher's Translations window chose ("<this DLL's folder>\
   Translation.ini": file=<the translation's full path>, else the copy "Translation.txt" beside it) and from then
   on the game shows it.

   HOW.  Every line of the game is a static record {id, key*, text*, override*} (from 0x4F5618; the string
   manager's constructor 0x450200 indexes them by id).  The game's own lookup, theStringManager::GetString
   0x44FD90, and its template filler GetStringFromNameGenderTemplate 0x44FDD0 return the override when it is set,
   else the text: the game's own localisation hook (it fills overrides from an "sm.xml" that the game does not
   ship).  This DLL sets the override of each translated line to its translation.  No code of the game's lookup is
   changed, so every other DLL that calls or checks it (vf1fun, vf1logs' pin of 0x44FD90) sees it as it is.

   ROOM.  native/vf1tr/vf1tr_limits.h (tools/build_vf1_translation_limits.py, from the vanilla code): a line the
   game strncpy's into a fixed field gets that field less its NUL; a line it sprintf's, strncat's or copies byte by
   byte gets its English length; every line at most VF1TR_MAX_LINE.  A longer translation is refused (English
   stays).  The eight copies whose line comes from data (an item, an event, a caller's table) are each redirected
   through a guard here (call rel32 -> guard -> the call's own target): a translated line reaching one is handed
   on cut to its English length, so those copies never hold more than in the English game.

   No choice, "English (original)", a missing or unreadable file, a file for another game: nothing is changed.
   A bad line (a broken placeholder, a changed English, too long, a line that is never translated) shows English;
   the file's other lines still work.  Every problem goes to "Translations.log" beside the DLL (line numbers,
   never the text).

   TEXT.  The game draws bytes.  Without the Unicode settings the translation is written in Windows-1252 (Latin-1
   and the usual quotes and dashes; any other letter as '?'); with vf1text.dll or vf1font.dll loaded (Render
   Unicode with In-Game Fonts / Use Unicode Font, loaded before this DLL) it is passed on as UTF-8, which they draw.

   Ported from the Fish and Plant Tycoon Fix Patcher's native/ftfp_translations. */
#include <windows.h>
#include <intrin.h>
#include "translation_text.h"
#include "vf1tr_limits.h"

#pragma intrinsic(_ReturnAddress)

#define AT(base, offset, type) (*(type *)((char *)(base) + (offset)))

EXTERN_C IMAGE_DOS_HEADER __ImageBase;

#define VF1TR_TABLE 0x004F5618u
#define VF1TR_RECORDS 0x66C
#define VF1TR_MAX_ID 0x675
#define VF1TR_MAX_LINE 1000
#define TR_ABSOLUTE_MAX VF1TR_MAX_LINE
#define MAX_FILE (8 * 1024 * 1024)
#define LOG_LINES 40
#define IMAGE_LOW 0x00400000u
#define IMAGE_HIGH 0x00898000u

static int slen(const char *s) { int n = 0; while (s[n]) ++n; return n; }
static int wlen(const wchar_t *s) { int n = 0; while (s[n]) ++n; return n; }
static void wcopy(wchar_t *to, const wchar_t *from) { while ((*to++ = *from++) != 0) {} }
static void wcat(wchar_t *to, const wchar_t *from) { wcopy(to + wlen(to), from); }
static void bcopy_(char *to, const char *from, int n) { int k; for (k = 0; k < n; ++k) to[k] = from[k]; }
static int bsame(const char *a, const char *b) { while (*a && *a == *b) { ++a; ++b; } return *a == *b; }
static int starts(tt_span line, const char *word) {
    int k;
    for (k = 0; word[k]; ++k) if (k >= line.n || tt_lower((unsigned char)line.s[k]) != word[k]) return 0;
    return 1;
}

typedef struct record { unsigned int id; const char *key; const char *text; const char *override; } record;

typedef struct row {
    int line;
    int id;
    const char *english;             /* UTF-8, from the file */
    int english_n;
    char *english_game;              /* the English as the game holds it (Windows-1252) */
    const char *translation;         /* UTF-8, choices still in */
    int translation_n;
    char *out;                       /* the translation as the game gets it */
    record *rec;
} row;

static int installed = 0;
static int text_mode = 0;            /* 0 Windows-1252, 1 UTF-8 */
static int plural_rule = TT_EN;
static row *rows = NULL;
static int row_count = 0;
static row *by_id[VF1TR_MAX_ID + 1];
static int used = 0, refused = 0, guarded = 0;
static wchar_t folder[1024];
static char file_label[200];
static char log_text[4096];
static int log_at = 0;
static char head_text[1024];
static int head_at = 0;
static int log_lines = 0;

/* ----------------------------------------------------------------- memory and the log */

static void *tr_alloc(SIZE_T n) { return HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, n == 0 ? 1 : n); }

static void log_add(const char *text) {
    while (*text && log_at < (int)sizeof log_text - 1) log_text[log_at++] = *text++;
    log_text[log_at] = 0;
}

static void head_add(const char *text) {
    while (*text && head_at < (int)sizeof head_text - 1) head_text[head_at++] = *text++;
    head_text[head_at] = 0;
}

static const char *number(int v) {
    static char digits[16];
    int at = 15;
    unsigned int u = v < 0 ? 0u : (unsigned int)v;
    digits[15] = 0;
    do { digits[--at] = (char)('0' + u % 10u); u /= 10u; } while (u && at > 0);
    return digits + at;
}

static void log_refused(int line, const char *why) {
    ++refused;
    if (++log_lines > LOG_LINES) return;
    log_add("  line ");
    log_add(number(line));
    log_add(": ");
    log_add(why);
    log_add(" (shows English)\r\n");
}

static void write_log(void) {
    static const char bom[] = "\xEF\xBB\xBF";
    wchar_t path[1100];
    HANDLE file;
    DWORD written;
    if (folder[0] == 0 || wlen(folder) > 1000) return;
    wcopy(path, folder);
    wcat(path, L"Translations.log");
    file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    WriteFile(file, bom, 3, &written, NULL);
    WriteFile(file, head_text, (DWORD)head_at, &written, NULL);
    WriteFile(file, log_text, (DWORD)log_at, &written, NULL);
    CloseHandle(file);
}

/* ----------------------------------------------------------------- files */

static unsigned char *read_file(const wchar_t *path, int *size) {
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL, NULL);
    DWORD low, high = 0, got = 0;
    unsigned char *data;
    if (file == INVALID_HANDLE_VALUE) return NULL;
    low = GetFileSize(file, &high);
    if (low == INVALID_FILE_SIZE || high != 0 || low > MAX_FILE) { CloseHandle(file); return NULL; }
    data = (unsigned char *)tr_alloc(low + 4);
    if (data == NULL || (low > 0 && (!ReadFile(file, data, low, &got, NULL) || got != low))) {
        CloseHandle(file);
        return NULL;
    }
    CloseHandle(file);
    *size = (int)low;
    return data;
}

static int utf8_to_wide(const char *s, int n, wchar_t *out, int cap) {
    tt_out o;
    int i = 0;
    o.buf = (char *)out;
    o.cap = cap;
    o.mode = 2;
    o.at = 0;
    o.overflow = 0;
    while (i < n) tt_put_cp(&o, tt_next_cp(s, n, &i));
    if (o.overflow || o.at >= cap) return 0;
    out[o.at] = 0;
    return 1;
}

/* "<folder>\Translation.ini": the chosen file (file=...).  The translation's bytes, or NULL for English. */
static unsigned char *chosen_file(int *size) {
    wchar_t path[1100];
    int n = 0, i = 0;
    unsigned char *ini, *data = NULL;
    char *text;
    int text_n;
    wcopy(path, folder);
    wcat(path, L"Translation.ini");
    ini = read_file(path, &n);
    if (ini == NULL) { log_add("Translations: no translation chosen (English)\r\n"); return NULL; }
    text = (char *)tr_alloc((SIZE_T)n * 2 + 16);
    text_n = text != NULL ? tt_decode(ini, n, text, n * 2 + 16) : -1;
    if (text_n < 0) { log_add("Translations: Translation.ini is not UTF-8 (English)\r\n"); return NULL; }
    while (i < text_n) {
        int start = i, end;
        tt_span line, value;
        while (i < text_n && text[i] != '\n' && text[i] != '\r') ++i;
        end = i;
        while (i < text_n && (text[i] == '\n' || text[i] == '\r')) ++i;
        line.s = text + start;
        line.n = end - start;
        line = tt_strip(line);
        if (line.n > 5 && starts(line, "file=")) {
            value.s = line.s + 5;
            value.n = line.n - 5;
            value = tt_strip(value);
            if (value.n > 0 && utf8_to_wide(value.s, value.n, path, 1060)) {
                int k = value.n, j;
                data = read_file(path, size);
                while (k > 0 && value.s[k - 1] != '\\' && value.s[k - 1] != '/') --k;
                for (j = 0; k < value.n && j < (int)sizeof file_label - 1; ++j, ++k) file_label[j] = value.s[k];
                file_label[j] = 0;
            }
        }
    }
    if (data == NULL && file_label[0] != 0) {
        wcopy(path, folder);
        wcat(path, L"Translation.txt");
        data = read_file(path, size);
        if (data != NULL) log_add("Translations: the chosen file was not found; using the copy Translation.txt\r\n");
    }
    if (data == NULL && file_label[0] != 0) log_add("Translations: the chosen file could not be read (English)\r\n");
    if (file_label[0] == 0) log_add("Translations: English (original)\r\n");
    return data;
}

/* ----------------------------------------------------------------- the game's lines */

static int is_text(const void *p) { return (unsigned int)(UINT_PTR)p >= IMAGE_LOW && (unsigned int)(UINT_PTR)p < IMAGE_HIGH; }

/* The record of a string id, found as the string manager's constructor finds it. */
static record *record_of(int id) {
    record *r = (record *)(UINT_PTR)VF1TR_TABLE;
    int k;
    if (id < 1 || id > VF1TR_MAX_ID) return NULL;
    for (k = 0; k < VF1TR_RECORDS; ++k) {
        if ((int)r[k].id == id) {
            if (!is_text(r[k].key) || !is_text(r[k].text) || r[k].key[0] != 'e') return NULL;
            return &r[k];
        }
    }
    return NULL;
}

static int in_list(const unsigned short *list, int id) {
    int k;
    for (k = 0; list[k] != 0; ++k) if (list[k] == id) return 1;
    return 0;
}

/* The most a line may hold, in UTF-8 bytes (patcher/vf1_translation_strings.room). */
static int room(int id, int english_bytes) {
    int best = VF1TR_MAX_LINE, k;
    for (k = 0; VF1TR_STRNCPY_ROOM[k].id != 0; ++k) {
        if (VF1TR_STRNCPY_ROOM[k].id == id) {
            int r = VF1TR_STRNCPY_ROOM[k].room > english_bytes ? VF1TR_STRNCPY_ROOM[k].room : english_bytes;
            if (r < best) best = r;
        }
    }
    if (in_list(VF1TR_ENGLISH_LENGTH, id) && english_bytes < best) best = english_bytes;
    return best;
}

/* ----------------------------------------------------------------- reading the file */

static int field_decode(tt_span f, char *out) {
    int i = 0, o = 0;
    if (f.n >= 2 && f.s[0] == '"' && f.s[f.n - 1] == '"') {
        tt_span inner;
        char *w = out;
        inner.s = f.s + 1;
        inner.n = f.n - 2;
        for (i = 0; i < inner.n; ++i) {
            out[o++] = inner.s[i];
            if (inner.s[i] == '"' && i + 1 < inner.n && inner.s[i + 1] == '"') ++i;
        }
        f.s = out;
        f.n = o;
        o = 0;
        i = 0;
        while (i < f.n) {
            if (f.s[i] == '\\' && i + 1 < f.n && (f.s[i + 1] == 'n' || f.s[i + 1] == 't' || f.s[i + 1] == '\\')) {
                w[o++] = f.s[i + 1] == 'n' ? '\n' : f.s[i + 1] == 't' ? '\t' : '\\';
                i += 2;
            } else {
                w[o++] = f.s[i++];
            }
        }
        out[o] = 0;
        return o;
    }
    while (i < f.n) {
        if (f.s[i] == '\\' && i + 1 < f.n && (f.s[i + 1] == 'n' || f.s[i + 1] == 't' || f.s[i + 1] == '\\')) {
            out[o++] = f.s[i + 1] == 'n' ? '\n' : f.s[i + 1] == 't' ? '\t' : '\\';
            i += 2;
        } else {
            out[o++] = f.s[i++];
        }
    }
    out[o] = 0;
    return o;
}

static int hexval(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

static int key_char(unsigned char c, int id_part) {
    return (c >= 'a' && c <= 'z') || tt_is_digit(c) || c == '_' || c == '-' || c == '.'
        || (id_part && ((c >= 'A' && c <= 'Z') || c == '/'));
}

static int split_key(tt_span key, tt_span *source, tt_span *id, unsigned int *hash) {
    int slash = -1, tilde, i;
    for (i = 0; i < key.n; ++i) if (key.s[i] == '/') { slash = i; break; }
    if (slash <= 0 || key.n < slash + 11) return 0;
    tilde = key.n - 9;
    if (key.s[tilde] != '~' || tilde <= slash + 1) return 0;
    for (i = 0; i < slash; ++i) if (!key_char((unsigned char)key.s[i], 0)) return 0;
    for (i = slash + 1; i < tilde; ++i) if (!key_char((unsigned char)key.s[i], 1)) return 0;
    *hash = 0;
    for (i = tilde + 1; i < key.n; ++i) {
        int v = hexval(key.s[i]);
        if (v < 0) return 0;
        *hash = (*hash << 4) | (unsigned int)v;
    }
    source->s = key.s;
    source->n = slash;
    id->s = key.s + slash + 1;
    id->n = tilde - slash - 1;
    return 1;
}

static char *render_out(const char *s, int n, const tt_template *t, int mode) {
    tt_out o;
    char *buf = (char *)tr_alloc((SIZE_T)(TR_ABSOLUTE_MAX + 4) * 4);
    if (buf == NULL) return NULL;
    o.buf = buf;
    o.cap = TR_ABSOLUTE_MAX * 2;
    o.mode = mode;
    return tt_render(s, n, t, plural_rule, NULL, 0, 0, &o) < 0 ? NULL : buf;
}

/* The translation's size as the limits count it (translation_format.measure): the larger of every choice at its
   longest and the text the game is handed, in UTF-8 bytes. */
static int measure(const char *s, int n, const tt_template *t) {
    static char scratch[(TR_ABSOLUTE_MAX + 4) * 8];
    tt_out o;
    int a, b;
    o.buf = scratch;
    o.cap = TR_ABSOLUTE_MAX * 2;
    o.mode = 1;
    a = tt_render(s, n, t, plural_rule, NULL, 0, 1, &o);
    b = tt_render(s, n, t, plural_rule, NULL, 0, 0, &o);
    if (a < 0 || b < 0) return 0x7FFFFFFF;
    return a > b ? a : b;
}

static tt_template tmpl_english, tmpl_translation;

static int read_rows(const char *text, int n) {
    int i = 0, line_no = 0, header = 0, lines = 1, k, format_seen = 0, pool_at = 0;
    char *pool;
    tt_span code;
    static const char title[] = "Virtual Families";
    code.s = "en";
    code.n = 2;
    for (k = 0; k < n; ++k) if (text[k] == '\n' || text[k] == '\r') ++lines;
    rows = (row *)tr_alloc(sizeof(row) * (SIZE_T)lines);
    pool = (char *)tr_alloc((SIZE_T)n * 2 + 64);
    if (rows == NULL || pool == NULL) return 0;
    /* pass 1: the header and the information rows */
    while (i < n) {
        int start = i, end, ncols = 0;
        tt_span cols[4];
        ++line_no;
        while (i < n && text[i] != '\n' && text[i] != '\r') ++i;
        end = i;
        if (i < n && text[i] == '\r' && i + 1 < n && text[i + 1] == '\n') i += 2; else if (i < n) ++i;
        {
            tt_span whole;
            whole.s = text + start;
            whole.n = end - start;
            if (tt_strip(whole).n == 0 || text[start] == '#') continue;
        }
        {
            int c = start;
            while (ncols < 4) {
                int e = c;
                while (e < end && text[e] != '\t') ++e;
                cols[ncols].s = text + c;
                cols[ncols].n = e - c;
                ++ncols;
                if (e >= end) break;
                c = e + 1;
            }
        }
        if (!header) {
            char a[72], b[72], c3[72];
            tt_span x, y, z;
            if (ncols < 3 || cols[0].n > 64 || cols[1].n > 64 || cols[2].n > 64) {
                log_add("Translations: the file has no header row (English)\r\n");
                return 0;
            }
            x.s = a; x.n = field_decode(cols[0], a); y.s = b; y.n = field_decode(cols[1], b); z.s = c3; z.n = field_decode(cols[2], c3);
            if (!tt_span_is(tt_strip(x), "key") || !tt_span_is(tt_strip(y), "english") || !tt_span_is(tt_strip(z), "translation")) {
                log_add("Translations: the file has no header row (English)\r\n");
                return 0;
            }
            header = 1;
            continue;
        }
        if (ncols < 2) continue;
        {
            tt_span key = tt_strip(cols[0]);
            int info = key.n > 0 && (key.s[0] == '@' || (key.n >= 3 && (unsigned char)key.s[0] == 0xEF
                                                         && (unsigned char)key.s[1] == 0xBC && (unsigned char)key.s[2] == 0xA0));
            tt_span name, eng, val;
            char *e = pool + pool_at, *v;
            if (!info) continue;
            name.s = key.s + (key.s[0] == '@' ? 1 : 3);
            name.n = key.n - (key.s[0] == '@' ? 1 : 3);
            if (cols[1].n > 256 || (ncols > 2 && cols[2].n > 256)) continue;
            eng.s = e; eng.n = field_decode(cols[1], e);
            v = e + eng.n + 1;
            val.s = v; val.n = ncols > 2 ? field_decode(cols[2], v) : 0;
            if (ncols <= 2) v[0] = 0;
            if (tt_exact_case(name, "format") && !format_seen) {
                tt_span f = tt_strip(val.n > 0 ? val : eng);
                int major = 0, j = 0;
                format_seen = 1;
                while (j < f.n && f.s[j] != '.') {
                    if (!tt_is_digit((unsigned char)f.s[j]) || major > 1000) { log_add("Translations: @format is not a version (English)\r\n"); return 0; }
                    major = major * 10 + (f.s[j] - '0');
                    ++j;
                }
                if (j == 0) { log_add("Translations: @format is not a version (English)\r\n"); return 0; }
                if (major > 1) { log_add("Translations: the file is a newer format than this DLL reads (English)\r\n"); return 0; }
            } else if (tt_exact_case(name, "game") && !(header & 2)) {
                tt_span g = tt_strip(eng), want;
                want.s = title;
                want.n = slen(title);
                header |= 2;
                if (!tt_span_eq(g, want)) { log_add("Translations: the file is for another game (English)\r\n"); return 0; }
            } else if (tt_exact_case(name, "code") && !(header & 4)) {
                header |= 4;
                code = val;
                pool_at += eng.n + val.n + 2;
            }
        }
    }
    if (!header) { log_add("Translations: the file has no header row (English)\r\n"); return 0; }
    if (!(header & 2)) { log_add("Translations: the file has no @game row (English)\r\n"); return 0; }
    plural_rule = tt_rule_for(code);
    /* pass 2: the rows */
    i = 0;
    line_no = 0;
    header = 0;
    while (i < n) {
        int start = i, end, ncols = 0, v = 0, j;
        tt_span cols[4], key, source, id;
        unsigned int hash;
        row *r;
        ++line_no;
        while (i < n && text[i] != '\n' && text[i] != '\r') ++i;
        end = i;
        if (i < n && text[i] == '\r' && i + 1 < n && text[i + 1] == '\n') i += 2; else if (i < n) ++i;
        {
            tt_span whole;
            whole.s = text + start;
            whole.n = end - start;
            if (tt_strip(whole).n == 0 || text[start] == '#') continue;
        }
        if (!header) { header = 1; continue; }
        {
            int c = start;
            while (ncols < 4) {
                int e = c;
                while (e < end && text[e] != '\t') ++e;
                cols[ncols].s = text + c;
                cols[ncols].n = e - c;
                ++ncols;
                if (e >= end) break;
                c = e + 1;
            }
        }
        if (ncols < 2) continue;
        key = tt_strip(cols[0]);
        if (key.n > 0 && (key.s[0] == '@' || (unsigned char)key.s[0] == 0xEF)) continue;
        if (ncols < 3 || cols[2].n == 0) continue;                            /* not translated */
        if (!split_key(key, &source, &id, &hash)) { log_refused(line_no, "the key is not a valid key"); continue; }
        r = &rows[row_count];
        r->line = line_no;
        r->english = pool + pool_at;
        r->english_n = field_decode(cols[1], pool + pool_at);
        pool_at += r->english_n + 1;
        r->translation = pool + pool_at;
        r->translation_n = field_decode(cols[2], pool + pool_at);
        pool_at += r->translation_n + 1;
        if (r->translation_n == 0) continue;
        if (tt_sha256_head((const unsigned char *)r->english, (unsigned int)r->english_n) != hash) {
            log_refused(line_no, "the English column does not match the key");
            continue;
        }
        if (!tt_span_is(source, "strings")) { log_refused(line_no, "unknown source"); continue; }
        for (j = 0; j < id.n; ++j) {
            if (!tt_is_digit((unsigned char)id.s[j]) || v > 100000) { v = -1; break; }
            v = v * 10 + (id.s[j] - '0');
        }
        if (v < 1 || v > VF1TR_MAX_ID || id.n == 0) { log_refused(line_no, "no such game line"); continue; }
        r->id = v;
        if (in_list(VF1TR_NEVER, v)) { log_refused(line_no, "this line is never translated"); continue; }
        r->rec = record_of(v);
        if (r->rec == NULL) { log_refused(line_no, "no such game line"); continue; }
        if (!tt_translation_ok(r->english, r->english_n, r->translation, r->translation_n, &tmpl_english, &tmpl_translation)) {
            log_refused(line_no, "the placeholders or choices do not match the English");
            continue;
        }
        if (measure(r->translation, r->translation_n, &tmpl_translation) > room(v, r->english_n)) {
            log_refused(line_no, "too long for its space");
            continue;
        }
        r->english_game = render_out(r->english, r->english_n, &tmpl_english, 0);
        if (r->english_game == NULL || !bsame(r->english_game, r->rec->text)) {
            log_refused(line_no, "the game's English is not this line's English");
            continue;
        }
        r->out = render_out(r->translation, r->translation_n, &tmpl_translation, text_mode);
        if (r->out == NULL) { log_refused(line_no, "could not be written"); continue; }
        if (by_id[v] != NULL) continue;                                      /* the same line again: the first counts */
        by_id[v] = r;
        ++row_count;
        ++used;
    }
    return 1;
}

/* ----------------------------------------------------------------- the guards */

static DWORD guard_next[VF1TR_GUARD_COUNT];

static int guard_index(void *return_address) {
    unsigned int at = (unsigned int)(UINT_PTR)return_address - 5u;
    int k;
    for (k = 0; k < VF1TR_GUARD_COUNT; ++k) if (VF1TR_GUARDS[k].call == at) return k;
    return -1;
}

static const row *row_of_out(const void *p) {
    int k;
    if (p == NULL) return NULL;
    for (k = 1; k <= VF1TR_MAX_ID; ++k) if (by_id[k] != NULL && (const void *)by_id[k]->out == p) return by_id[k];
    return NULL;
}

/* A translated line cut to its English length (at a whole letter); anything else as it is. */
static char cut_slots[8][TR_ABSOLUTE_MAX + 8];
static int cut_next = 0;

static const char *cut(const char *s) {
    const row *r = row_of_out(s);
    int le, lt;
    char *slot;
    if (r == NULL) return s;
    le = slen(r->english_game);
    lt = slen(s);
    if (lt <= le) return s;
    if (text_mode == 1) while (le > 0 && ((unsigned char)s[le] & 0xC0) == 0x80) --le;
    slot = cut_slots[cut_next++ & 7];
    bcopy_(slot, s, le);
    slot[le] = 0;
    return slot;
}

typedef char *(__cdecl *copy_fn)(char *, const char *, size_t);
typedef int (__cdecl *sprintf_fn)(char *, const char *, ...);

static char *__cdecl guard_copy(char *dst, const char *src, size_t n) {
    int k = guard_index(_ReturnAddress());
    const char *use = src;
    if (k < 0) return dst;                     /* never: only the guarded calls come here */
    __try { use = cut(src); } __except (EXCEPTION_EXECUTE_HANDLER) { use = src; }
    return ((copy_fn)(UINT_PTR)guard_next[k])(dst, use, n);
}

static char sprintf_t[(TR_ABSOLUTE_MAX + 64) * 10];
static char sprintf_e[(TR_ABSOLUTE_MAX + 64) * 10];

/* sprintf(dst, format, up to 8 more): a translated format or argument may make the text no longer than the
   English format and arguments make it. */
static int __cdecl guard_sprintf(char *dst, const char *format, DWORD a0, DWORD a1, DWORD a2, DWORD a3, DWORD a4,
                                 DWORD a5, DWORD a6, DWORD a7) {
    int k = guard_index(_ReturnAddress()), changed = 0, q, lt, le;
    DWORD a[8], e[8];
    const char *fe = format;
    sprintf_fn next;
    if (k < 0) return 0;
    next = (sprintf_fn)(UINT_PTR)guard_next[k];
    a[0] = a0; a[1] = a1; a[2] = a2; a[3] = a3; a[4] = a4; a[5] = a5; a[6] = a6; a[7] = a7;
    __try {
        const row *r = row_of_out(format);
        if (r != NULL) { fe = r->english_game; changed = 1; }
        for (q = 0; q < 8; ++q) {
            const row *x = row_of_out((const void *)(UINT_PTR)a[q]);
            e[q] = x != NULL ? (DWORD)(UINT_PTR)x->english_game : a[q];
            if (x != NULL) changed = 1;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        changed = 0;
    }
    if (!changed) return next(dst, format, a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]);
    lt = next(sprintf_t, format, a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]);
    le = next(sprintf_e, fe, e[0], e[1], e[2], e[3], e[4], e[5], e[6], e[7]);
    if (lt < 0 || le < 0) return next(dst, fe, e[0], e[1], e[2], e[3], e[4], e[5], e[6], e[7]);
    if (lt > le) {
        lt = le;
        if (text_mode == 1) while (lt > 0 && ((unsigned char)sprintf_t[lt] & 0xC0) == 0x80) --lt;
    }
    bcopy_(dst, sprintf_t, lt);
    dst[lt] = 0;
    return lt;
}

static int write_code(unsigned int at, const unsigned char *bytes, int n) {
    DWORD old, ignored;
    int k;
    if (!VirtualProtect((void *)(UINT_PTR)at, (SIZE_T)n, PAGE_EXECUTE_READWRITE, &old)) return 0;
    for (k = 0; k < n; ++k) ((unsigned char *)(UINT_PTR)at)[k] = bytes[k];
    VirtualProtect((void *)(UINT_PTR)at, (SIZE_T)n, old, &ignored);
    FlushInstructionCache(GetCurrentProcess(), (void *)(UINT_PTR)at, (SIZE_T)n);
    return 1;
}

/* Every guarded call must be a call (to its CRT function, or to an earlier DLL's hook, which is chained); else
   nothing is installed. */
static int install_guards(void) {
    int k;
    for (k = 0; k < VF1TR_GUARD_COUNT; ++k) {
        const unsigned char *code = (const unsigned char *)(UINT_PTR)VF1TR_GUARDS[k].call;
        DWORD to;
        MEMORY_BASIC_INFORMATION info;
        if (code[0] != 0xE8) return 0;
        to = VF1TR_GUARDS[k].call + 5u + *(const DWORD *)(code + 1);
        if (VirtualQuery((const void *)(UINT_PTR)to, &info, sizeof info) != sizeof info || info.State != MEM_COMMIT
            || (info.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)) == 0)
            return 0;
        guard_next[k] = to;
    }
    for (k = 0; k < VF1TR_GUARD_COUNT; ++k) {
        unsigned char call[5];
        DWORD target = VF1TR_GUARDS[k].kind == 1 ? (DWORD)(UINT_PTR)guard_sprintf : (DWORD)(UINT_PTR)guard_copy;
        DWORD rel = target - (VF1TR_GUARDS[k].call + 5u);
        if (guard_next[k] == target) continue;
        call[0] = 0xE8;
        call[1] = (unsigned char)rel; call[2] = (unsigned char)(rel >> 8);
        call[3] = (unsigned char)(rel >> 16); call[4] = (unsigned char)(rel >> 24);
        if (!write_code(VF1TR_GUARDS[k].call, call, 5)) return 0;
        ++guarded;
    }
    return 1;
}

/* ----------------------------------------------------------------- installing */

static int is_this_game(void) {
    record *r = record_of(1);
    return r != NULL && *(const unsigned char *)(UINT_PTR)0x0044FD90u != 0;
}

static void own_folder(void) {
    DWORD n = GetModuleFileNameW((HMODULE)&__ImageBase, folder, 1000);
    wchar_t *slash;
    if (n == 0 || n >= 1000) { folder[0] = 0; return; }
    folder[n] = 0;
    slash = folder + n;
    while (slash > folder && slash[-1] != L'\\' && slash[-1] != L'/') --slash;
    *slash = 0;
}

static int started = 0;

__declspec(dllexport) int __cdecl VF1Tr_Startup(void) {
    unsigned char *data;
    char *text;
    int size = 0, text_n, k;
    if (started) return installed;
    started = 1;
    __try {
        own_folder();
        if (!is_this_game()) {
            log_add("Translations: NOT installed; this is not the game this build expects\r\n");
        } else if ((data = chosen_file(&size)) != NULL) {
            text_mode = (GetModuleHandleW(L"vf1text.dll") != NULL || GetModuleHandleW(L"vf1font.dll") != NULL) ? 1 : 0;
            text = (char *)tr_alloc((SIZE_T)size * 2 + 16);
            text_n = text != NULL ? tt_decode(data, size, text, size * 2 + 16) : -1;
            if (text_n < 0) {
                log_add("Translations: the file is not UTF-8 or UTF-16 with a byte-order mark (English)\r\n");
            } else if (read_rows(text, text_n)) {
                if (used == 0) {
                    log_add("Translations: no translated line could be used (English)\r\n");
                } else if (!install_guards()) {
                    log_add("Translations: NOT installed; a guarded call is not the code this build expects\r\n");
                } else {
                    for (k = 1; k <= VF1TR_MAX_ID; ++k) if (by_id[k] != NULL) by_id[k]->rec->override = by_id[k]->out;
                    installed = 1;
                }
            }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        log_add("Translations: stopped by an error; the game stays in English where it was not yet changed\r\n");
    }
    if (installed) {
        head_add("Translations: installed (");
        head_add(file_label[0] ? file_label : "Translation.txt");
        head_add("): ");
        head_add(number(used));
        head_add(" lines used, ");
        head_add(number(guarded));
        head_add(" copies guarded, ");
        head_add(text_mode ? "UTF-8 text" : "Windows-1252 text");
        head_add("\r\n");
    }
    if (refused > 0) {
        head_add("Translations: ");
        head_add(number(refused));
        head_add(" line(s) show English:\r\n");
    }
    write_log();
    return installed;
}

/* The line's override for a string id now (tests and other DLLs): the translation, or NULL (English). */
__declspec(dllexport) const char *__cdecl VF1Tr_Translation(int id) {
    return id >= 1 && id <= VF1TR_MAX_ID && by_id[id] != NULL && installed ? by_id[id]->out : NULL;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(instance);
    return TRUE;
}
