// Accessible Chess optional libcbh bridge.
//
// This file contains only protocol/adaptation code written for Accessible
// Chess. It links to an external libcbh build at CI/runtime. The linked binary
// inherits libcbh's distribution obligations; it is not part of the default
// Accessible Chess package unless separately approved.

#include <cbh.h>
#include <interface.h>

#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <type_traits>
#include <variant>
#include <vector>

#ifndef LIBCBH_SOURCE_COMMIT
#define LIBCBH_SOURCE_COMMIT "unknown"
#endif

namespace {

bool is_utf8_continuation(unsigned char value) {
    return value >= 0x80 && value <= 0xBF;
}

std::size_t valid_utf8_sequence_length(const std::string& value, std::size_t index) {
    const auto byte = [&value](std::size_t position) {
        return static_cast<unsigned char>(value[position]);
    };
    const unsigned char first = byte(index);
    const std::size_t remaining = value.size() - index;
    if (first >= 0xC2 && first <= 0xDF) {
        return remaining >= 2 && is_utf8_continuation(byte(index + 1)) ? 2 : 0;
    }
    if (remaining >= 3 && first >= 0xE0 && first <= 0xEF) {
        const unsigned char second = byte(index + 1);
        const unsigned char third = byte(index + 2);
        if (!is_utf8_continuation(third)) {
            return 0;
        }
        if (first == 0xE0) {
            return second >= 0xA0 && second <= 0xBF ? 3 : 0;
        }
        if (first == 0xED) {
            return second >= 0x80 && second <= 0x9F ? 3 : 0;
        }
        return is_utf8_continuation(second) ? 3 : 0;
    }
    if (remaining >= 4 && first >= 0xF0 && first <= 0xF4) {
        const unsigned char second = byte(index + 1);
        const unsigned char third = byte(index + 2);
        const unsigned char fourth = byte(index + 3);
        if (!is_utf8_continuation(third) || !is_utf8_continuation(fourth)) {
            return 0;
        }
        if (first == 0xF0) {
            return second >= 0x90 && second <= 0xBF ? 4 : 0;
        }
        if (first == 0xF4) {
            return second >= 0x80 && second <= 0x8F ? 4 : 0;
        }
        return is_utf8_continuation(second) ? 4 : 0;
    }
    return 0;
}

std::string json_string(const std::string& value) {
    std::ostringstream out;
    out << '"';
    for (std::size_t index = 0; index < value.size();) {
        const unsigned char c = static_cast<unsigned char>(value[index]);
        switch (c) {
        case '"': out << "\\\""; ++index; break;
        case '\\': out << "\\\\"; ++index; break;
        case '\b': out << "\\b"; ++index; break;
        case '\f': out << "\\f"; ++index; break;
        case '\n': out << "\\n"; ++index; break;
        case '\r': out << "\\r"; ++index; break;
        case '\t': out << "\\t"; ++index; break;
        default:
            if (c < 0x20) {
                out << "\\u00" << std::hex << std::setw(2) << std::setfill('0')
                    << static_cast<unsigned int>(c) << std::dec;
                ++index;
            } else if (c < 0x80) {
                out << static_cast<char>(c);
                ++index;
            } else {
                // Preserve already-valid UTF-8 as Unicode.  libcbh otherwise
                // exposes no charset contract, so an invalid high byte is
                // retained deterministically as U+00XX rather than guessed as
                // a proprietary/code-page character or emitted as invalid JSON.
                const std::size_t length = valid_utf8_sequence_length(value, index);
                if (length) {
                    out.write(value.data() + index, static_cast<std::streamsize>(length));
                    index += length;
                } else {
                    out << "\\u00" << std::hex << std::setw(2) << std::setfill('0')
                        << static_cast<unsigned int>(c) << std::dec;
                    ++index;
                }
            }
        }
    }
    out << '"';
    return out.str();
}

std::string scid_eco_main_to_pgn(unsigned int value) {
    // Pinned libcbh intentionally drops ChessBase ECO subcodes and exposes the
    // Scid main-code sequence 1 + 131*n for A00..E99.  Zero is unknown.  Keep
    // this strict: an unexpected non-main-code value is not converted.
    constexpr unsigned int stride = 131;
    constexpr unsigned int main_codes = 500;
    if (value == 0 || (value - 1) % stride != 0) {
        return {};
    }
    const unsigned int index = (value - 1) / stride;
    if (index >= main_codes) {
        return {};
    }
    const char letter = static_cast<char>('A' + index / 100);
    std::ostringstream out;
    out << letter << std::setw(2) << std::setfill('0') << index % 100;
    return out.str();
}

bool has_exact_tag(const std::vector<Tag>& tags, const std::string& name) {
    for (const auto& tag : tags) {
        if (tag.tag == name) {
            return true;
        }
    }
    return false;
}

void write_comment(std::ostream& out, const Comment& comment) {
    std::visit(
        [&out](const auto& value) {
            using T = std::decay_t<decltype(value)>;
            if constexpr (std::is_same_v<T, TextBeforeComment>) {
                out << "{\"kind\":\"text_before\",\"lang\":"
                    << static_cast<unsigned int>(value.lang)
                    << ",\"text\":" << json_string(value.text) << '}';
            } else if constexpr (std::is_same_v<T, TextAfterComment>) {
                out << "{\"kind\":\"text_after\",\"lang\":"
                    << static_cast<unsigned int>(value.lang)
                    << ",\"text\":" << json_string(value.text) << '}';
            } else if constexpr (std::is_same_v<T, ArrowComment>) {
                out << "{\"kind\":\"arrow\",\"from\":"
                    << static_cast<unsigned int>(value.from)
                    << ",\"to\":" << static_cast<unsigned int>(value.to)
                    << ",\"color\":" << json_string(value.color) << '}';
            } else if constexpr (std::is_same_v<T, SquareComment>) {
                out << "{\"kind\":\"square\",\"square\":"
                    << static_cast<unsigned int>(value.sq)
                    << ",\"color\":" << json_string(value.color) << '}';
            } else if constexpr (std::is_same_v<T, SymbolComment>) {
                out << "{\"kind\":\"symbol\",\"symbol\":"
                    << static_cast<unsigned int>(value.symbol)
                    << ",\"evaluation\":"
                    << static_cast<unsigned int>(value.evaluation)
                    << ",\"prefix\":" << static_cast<unsigned int>(value.prefix)
                    << '}';
            }
        },
        comment);
}

void write_move(std::ostream& out, const AnnotatedMove& move) {
    if (move.promote == static_cast<byte>(-1)) {
        out << "{\"kind\":\"push\"}";
        return;
    }
    if (move.promote == static_cast<byte>(-2)) {
        out << "{\"kind\":\"pop\"}";
        return;
    }
    if (move.promote == static_cast<byte>(-3)) {
        out << "{\"kind\":\"skip\"}";
        return;
    }

    out << "{\"kind\":\"move\",\"from\":"
        << static_cast<unsigned int>(move.from)
        << ",\"to\":" << static_cast<unsigned int>(move.to)
        << ",\"promote\":" << static_cast<unsigned int>(move.promote)
        << ",\"comments\":[";
    for (std::size_t i = 0; i < move.comments.size(); ++i) {
        if (i) out << ',';
        write_comment(out, move.comments[i]);
    }
    out << "]}";
}

void write_tags(std::ostream& out, const std::vector<Tag>& tags, unsigned int eco) {
    out << '[';
    bool wrote = false;
    for (const auto& tag : tags) {
        if (wrote) out << ',';
        out << "{\"name\":" << json_string(tag.tag)
            << ",\"value\":" << json_string(tag.value) << '}';
        wrote = true;
    }

    // libcbh exposes ECO as a Scid main-code integer rather than a PGN tag.
    // Publish the loss-aware three-character main ECO only when the backend did
    // not already provide an explicit ECO tag.  The Python adapter also retains
    // the raw integer as CBH_ECO for audit/debug provenance.
    if (!has_exact_tag(tags, "ECO")) {
        const std::string canonical_eco = scid_eco_main_to_pgn(eco);
        if (!canonical_eco.empty()) {
            if (wrote) out << ',';
            out << "{\"name\":\"ECO\",\"value\":"
                << json_string(canonical_eco) << '}';
        }
    }
    out << ']';
}

void write_game(std::ostream& out, std::size_t index, const GameReturnValue& game) {
    out << "{\"index\":" << index
        << ",\"status\":\"decoded\""
        << ",\"start_fen\":" << json_string(game.startFen)
        << ",\"result\":" << static_cast<unsigned int>(game.result)
        << ",\"white_first\":" << json_string(game.whiteFirstName)
        << ",\"white_last\":" << json_string(game.whiteName)
        << ",\"black_first\":" << json_string(game.blackFirstName)
        << ",\"black_last\":" << json_string(game.blackName)
        << ",\"event\":" << json_string(game.eventTitle)
        << ",\"site\":" << json_string(game.eventPlace)
        << ",\"year\":" << game.gameDate.year
        << ",\"month\":" << game.gameDate.month
        << ",\"day\":" << game.gameDate.day
        << ",\"white_elo\":" << static_cast<unsigned int>(game.whiteElo)
        << ",\"black_elo\":" << static_cast<unsigned int>(game.blackElo)
        << ",\"eco\":" << static_cast<unsigned int>(game.eco)
        << ",\"round\":" << static_cast<unsigned int>(game.round)
        << ",\"subround\":" << static_cast<unsigned int>(game.subround)
        << ",\"tags\":";
    write_tags(out, game.tags, static_cast<unsigned int>(game.eco));

    // libcbh appends one structural MovePop when the root decoder returns.
    // It is backend control flow, not canonical game data. Nested pops occur
    // before this terminal element and remain in-range, so they are preserved.
    std::size_t move_count = game.annotatedMoves.size();
    if (move_count > 0 &&
        game.annotatedMoves.back().promote == static_cast<byte>(-2)) {
        --move_count;
    }

    out << ",\"moves\":[";
    for (std::size_t i = 0; i < move_count; ++i) {
        if (i) out << ',';
        write_move(out, game.annotatedMoves[i]);
    }
    out << "]}";
}

} // namespace

int main(int argc, char** argv) {
    if (argc != 3 || std::string(argv[1]) != "--json-v1") {
        std::cerr << "usage: libcbh-json-bridge --json-v1 <database.cbh>\n";
        return 64;
    }

    CbhCodec codec;
    const errorT open_error = codec.open(argv[2]);
    if (open_error != OK) {
        std::cerr << "libcbh open failed with code "
                  << static_cast<unsigned int>(open_error) << '\n';
        return 65;
    }

    std::cout << "{\"protocol\":\"accessible-chess-libcbh-v1\""
              << ",\"backend\":\"libcbh\""
              << ",\"backend_commit\":" << json_string(LIBCBH_SOURCE_COMMIT)
              << ",\"string_encoding\":\"utf8_or_byte_escape_u00xx\""
              << ",\"games\":[";

    const std::size_t count = codec.numGames();
    for (std::size_t index = 0; index < count; ++index) {
        if (index) std::cout << ',';
        GameReturnValue game;
        const errorT parse_error = codec.parseNext(game);
        if (parse_error != OK) {
            std::cout << "{\"index\":" << index
                      << ",\"status\":\"skipped\",\"error_code\":"
                      << static_cast<unsigned int>(parse_error) << '}';
            continue;
        }
        write_game(std::cout, index, game);
    }
    std::cout << "]}\n";
    return std::cout.good() ? 0 : 74;
}
