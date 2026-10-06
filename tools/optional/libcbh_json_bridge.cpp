// Accessible Chess optional libcbh bridge.
//
// This file contains only protocol/adaptation code written for Accessible
// Chess. It links to an external libcbh build at CI/runtime. The linked binary
// inherits libcbh's distribution obligations; it is not part of the default
// Accessible Chess package unless separately approved.

#include <cbh.h>
#include <interface.h>

#include <cctype>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <string_view>
#include <type_traits>
#include <variant>
#include <vector>

#ifndef LIBCBH_SOURCE_COMMIT
#define LIBCBH_SOURCE_COMMIT "unknown"
#endif

namespace {

constexpr std::string_view PINNED_LIBCBH_NAG_COMMIT =
    "9641c5c3949d8fb210b17dd9aa54455645843696";

// Protocol-v1 record-level adapter code. Deliberately outside libcbh's
 // errorT range: the record decoded, but Accessible Chess must not expose an
 // explicitly identified Chess960/Fischer Random game to the Standard core.
constexpr unsigned int UNSUPPORTED_CHESS960_RECORD = 960;

constexpr unsigned int canonicalize_pinned_evaluation_nag(nagT value) {
    // The pinned libcbh commit has already interpreted the raw ChessBase
    // evaluation byte before exposing SymbolComment. The independent pinned
    // ChessBase-export fixture establishes the canonical PGN value for these
    // exact raw codes. Reverse only transformations belonging to those
    // qualified codes; every other value remains untouched.
    switch (static_cast<unsigned int>(value)) {
    case 10: return 11;
    case 33: return 32;
    case 37: return 36;
    case 41: return 40;
    case 45: return 44;
    case 133: return 132;
    case 136:
    case 137:
        return 138;
    default:
        return static_cast<unsigned int>(value);
    }
}

constexpr unsigned int canonical_evaluation_nag(nagT value) {
    if (std::string_view(LIBCBH_SOURCE_COMMIT) != PINNED_LIBCBH_NAG_COMMIT) {
        return static_cast<unsigned int>(value);
    }
    return canonicalize_pinned_evaluation_nag(value);
}

static_assert(canonicalize_pinned_evaluation_nag(10) == 11);
static_assert(canonicalize_pinned_evaluation_nag(33) == 32);
static_assert(canonicalize_pinned_evaluation_nag(37) == 36);
static_assert(canonicalize_pinned_evaluation_nag(41) == 40);
static_assert(canonicalize_pinned_evaluation_nag(45) == 44);
static_assert(canonicalize_pinned_evaluation_nag(133) == 132);
static_assert(canonicalize_pinned_evaluation_nag(136) == 138);
static_assert(canonicalize_pinned_evaluation_nag(137) == 138);
static_assert(canonicalize_pinned_evaluation_nag(14) == 14);

std::string json_string(const std::string& value) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : value) {
        switch (c) {
        case '"': out << "\\\""; break;
        case '\\': out << "\\\\"; break;
        case '\b': out << "\\b"; break;
        case '\f': out << "\\f"; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            // libcbh exposes byte strings without an encoding contract. Keep
            // the JSON stream valid and preserve every byte deterministically.
            // Bytes >= 0x80 are represented one-to-one as U+00XX rather than
            // emitting possibly-invalid UTF-8.
            if (c < 0x20 || c >= 0x80) {
                out << "\\u00" << std::hex << std::setw(2) << std::setfill('0')
                    << static_cast<unsigned int>(c) << std::dec;
            } else {
                out << static_cast<char>(c);
            }
        }
    }
    out << '"';
    return out.str();
}

std::string normalized_ascii_token(const std::string& value) {
    std::string normalized;
    normalized.reserve(value.size());
    for (unsigned char c : value) {
        if (std::isalnum(c)) {
            normalized.push_back(static_cast<char>(std::tolower(c)));
        }
    }
    return normalized;
}

bool has_explicit_chess960_tag(const std::vector<Tag>& tags) {
    for (const Tag& tag : tags) {
        if (normalized_ascii_token(tag.tag) != "variant") {
            continue;
        }
        const std::string value = normalized_ascii_token(tag.value);
        if (value == "chess960" || value == "fischerrandom" || value == "frc") {
            return true;
        }
    }
    return false;
}

bool has_shredder_fen_castling_rights(const std::string& fen) {
    // Standard FEN castling rights use only KQkq or '-'. Rook-file rights
    // (A-H/a-h) are an explicit Shredder-FEN/X-FEN Chess960 transport signal.
    // A non-standard board layout alone is still allowed through Standard
    // position validation; no Chess960 rules are implemented here.
    std::istringstream input(fen);
    std::string board;
    std::string side;
    std::string castling;
    if (!(input >> board >> side >> castling)) {
        return false;
    }
    for (unsigned char c : castling) {
        if ((c >= 'A' && c <= 'H') || (c >= 'a' && c <= 'h')) {
            return true;
        }
    }
    return false;
}

bool is_explicit_chess960_record(const GameReturnValue& game) {
    return has_explicit_chess960_tag(game.tags) ||
           has_shredder_fen_castling_rights(game.startFen);
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
                    << canonical_evaluation_nag(value.evaluation)
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

void write_tags(std::ostream& out, const std::vector<Tag>& tags) {
    out << '[';
    for (std::size_t i = 0; i < tags.size(); ++i) {
        if (i) out << ',';
        out << "{\"name\":" << json_string(tags[i].tag)
            << ",\"value\":" << json_string(tags[i].value) << '}';
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
    write_tags(out, game.tags);

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
              << ",\"string_encoding\":\"byte_escape_u00xx\""
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
        if (is_explicit_chess960_record(game)) {
            std::cout << "{\"index\":" << index
                      << ",\"status\":\"skipped\",\"error_code\":"
                      << UNSUPPORTED_CHESS960_RECORD
                      << ",\"reason\":\"unsupported_chess960\"}";
            continue;
        }
        write_game(std::cout, index, game);
    }
    std::cout << "]}\n";
    return std::cout.good() ? 0 : 74;
}
