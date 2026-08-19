/*
 * main.c — RP2350 hardware TRNG streamer
 * ========================================
 * Minimal firmware: reads the RP2350's on-chip hardware TRNG via the
 * Pico SDK's pico_rand library and streams raw bytes to the host over
 * USB CDC serial, on request only (no unsolicited output).
 *
 * PROTOCOL (deliberately trivial, to keep this auditable):
 *   Host sends: single byte 'R'
 *   Device replies: exactly 256 raw bytes (2048 bits) of TRNG output.
 *   No headers, no framing, no length negotiation. One request byte
 *   in, 256 random bytes out, every time.
 *   (Changed from 32 bytes on 2026-08-14 for throughput -- same change
 *   as the Nucleo firmware. Reduces serial round-trips per 512-byte
 *   quorum refill from 16 to 2.)
 *
 * This firmware does NOT do any entropy processing (no debiasing, no
 * hashing, no mixing) — it hands over raw hardware TRNG output
 * unmodified. Any processing happens on the host side, in inspectable
 * Python, matching this project's pattern everywhere else.
 *
 * BINARY TRANSPORT NOTE (fix 2026-08-10):
 *   The output is RAW BINARY. The Pico stdio layer defaults to LF->CRLF
 *   translation, inserting a 0x0D before every 0x0A byte. On random data
 *   that biases the histogram AND corrupts stream alignment (a 32-byte
 *   chunk containing 0x0A emits 33+ bytes, desyncing host reads).
 *   CRLF translation is disabled at COMPILE TIME via three defines in
 *   CMakeLists.txt: PICO_STDIO_ENABLE_CRLF_SUPPORT=0,
 *   PICO_STDIO_USB_DEFAULT_CRLF=0, PICO_STDIO_DEFAULT_CRLF=0.
 *   We do NOT call stdio_set_translate_crlf() at runtime — poking the USB
 *   driver during init before the CDC link is up prevents enumeration.
 *   Output uses putchar_raw() which bypasses newline handling regardless.
 */

#include "pico/stdlib.h"
#include "pico/rand.h"

#define CHUNK_BYTES 256

int main() {
    stdio_init_all();

    while (true) {
        int c = getchar_timeout_us(1000000);  // 1s poll
        if (c == 'R') {
            uint8_t buf[CHUNK_BYTES];
            for (int i = 0; i < CHUNK_BYTES; i += 4) {
                uint32_t r = get_rand_32();
                buf[i]     = (uint8_t)(r >> 24);
                buf[i + 1] = (uint8_t)(r >> 16);
                buf[i + 2] = (uint8_t)(r >> 8);
                buf[i + 3] = (uint8_t)(r);
            }
            for (int i = 0; i < CHUNK_BYTES; i++) {
                putchar_raw(buf[i]);
            }
            stdio_flush();
        }
    }
    return 0;
}
