#define WIN32_LEAN_AND_MEAN
#include <windows.h>

/*
 * Accessible Chess portable launcher.
 *
 * Runtime contract:
 * - this executable lives at the extracted package root;
 * - the real product executable lives at App\\AccessibleChess.exe;
 * - LOCALAPPDATA is redirected to package-root\\data for the child only;
 * - launch-report.txt is created beside this executable for blind-user support;
 * - no shell, PowerShell, Python or installer is required at runtime.
 *
 * The release workflow links this file without the CRT. Keep this source on the
 * Win32 KERNEL32/USER32 surface so the launcher itself cannot gain a hidden
 * runtime dependency while solving a startup-dependency failure.
 */

#define AC_PATH_CAP 32768
#define AC_UTF8_CAP (AC_PATH_CAP * 4 + 4096)
#define AC_STARTUP_OBSERVE_MS 2500
#define AC_REPORT_RETRY_MS 100
#define AC_REPORT_RETRY_COUNT 40
#define ACCESSIBILITY_HOST_INIT_EXIT_CODE 71
#define SAFE_LOCAL_SERVER_INIT_EXIT_CODE 72

static WCHAR g_module[AC_PATH_CAP];
static WCHAR g_root[AC_PATH_CAP];
static WCHAR g_app_dir[AC_PATH_CAP];
static WCHAR g_core[AC_PATH_CAP];
static WCHAR g_data[AC_PATH_CAP];
static WCHAR g_report_path[AC_PATH_CAP];
static WCHAR g_command[AC_PATH_CAP * 2];
static WCHAR g_message[AC_PATH_CAP + 2048];
static WCHAR g_error_text[2048];
static CHAR g_utf8[AC_UTF8_CAP];
static STARTUPINFOW g_startup;
static PROCESS_INFORMATION g_process;

static SIZE_T ac_wlen(const WCHAR *value) {
    SIZE_T size = 0;
    if (value == NULL) return 0;
    while (value[size] != L'\0') ++size;
    return size;
}

static BOOL ac_copy(WCHAR *target, SIZE_T cap, const WCHAR *value) {
    SIZE_T index = 0;
    if (target == NULL || value == NULL || cap == 0) return FALSE;
    while (value[index] != L'\0') {
        if (index + 1 >= cap) return FALSE;
        target[index] = value[index];
        ++index;
    }
    target[index] = L'\0';
    return TRUE;
}

static BOOL ac_append(WCHAR *target, SIZE_T cap, const WCHAR *value) {
    SIZE_T used = ac_wlen(target);
    SIZE_T index = 0;
    if (used >= cap) return FALSE;
    while (value[index] != L'\0') {
        if (used + index + 1 >= cap) return FALSE;
        target[used + index] = value[index];
        ++index;
    }
    target[used + index] = L'\0';
    return TRUE;
}

static BOOL ac_path_join(WCHAR *target, SIZE_T cap, const WCHAR *base, const WCHAR *leaf) {
    SIZE_T used;
    if (!ac_copy(target, cap, base)) return FALSE;
    used = ac_wlen(target);
    if (used == 0) return FALSE;
    if (target[used - 1] != L'\\' && target[used - 1] != L'/') {
        if (!ac_append(target, cap, L"\\")) return FALSE;
    }
    return ac_append(target, cap, leaf);
}

static BOOL ac_parent_dir(WCHAR *target, SIZE_T cap, const WCHAR *path) {
    SIZE_T size;
    if (!ac_copy(target, cap, path)) return FALSE;
    size = ac_wlen(target);
    while (size > 0) {
        --size;
        if (target[size] == L'\\' || target[size] == L'/') {
            if (size == 2 && target[1] == L':') ++size;
            target[size] = L'\0';
            return TRUE;
        }
    }
    return FALSE;
}

static BOOL ac_append_u32(WCHAR *target, SIZE_T cap, DWORD value) {
    WCHAR digits[16];
    SIZE_T count = 0;
    SIZE_T index;
    if (value == 0) return ac_append(target, cap, L"0");
    while (value > 0 && count < 15) {
        digits[count++] = (WCHAR)(L'0' + (value % 10));
        value /= 10;
    }
    for (index = count; index > 0; --index) {
        WCHAR one[2];
        one[0] = digits[index - 1];
        one[1] = L'\0';
        if (!ac_append(target, cap, one)) return FALSE;
    }
    return TRUE;
}

static const WCHAR *ac_child_exit_reason(DWORD code) {
    if (code == ACCESSIBILITY_HOST_INIT_EXIT_CODE) return L"ACCESSIBILITY_HOST_INIT_FAILED";
    if (code == SAFE_LOCAL_SERVER_INIT_EXIT_CODE) return L"SAFE_LOCAL_SERVER_INIT_FAILED";
    return L"UNKNOWN_EARLY_EXIT";
}

static const WCHAR *ac_child_exit_user_detail(DWORD code) {
    if (code == ACCESSIBILITY_HOST_INIT_EXIT_CODE) {
        return L"Не вдалося ініціалізувати доступний WebView2/WinForms інтерфейс.";
    }
    if (code == SAFE_LOCAL_SERVER_INIT_EXIT_CODE) {
        return L"Не вдалося ініціалізувати безпечний локальний сервер WebView2.";
    }
    return L"Невідома рання помилка основної програми.";
}

static void ac_write_utf8(HANDLE handle, const WCHAR *text) {
    int bytes;
    DWORD written = 0;
    if (handle == NULL || handle == INVALID_HANDLE_VALUE || text == NULL) return;
    bytes = WideCharToMultiByte(
        CP_UTF8,
        WC_ERR_INVALID_CHARS,
        text,
        -1,
        g_utf8,
        AC_UTF8_CAP,
        NULL,
        NULL
    );
    if (bytes <= 1) return;
    WriteFile(handle, g_utf8, (DWORD)(bytes - 1), &written, NULL);
}

static void ac_write_line(HANDLE handle, const WCHAR *text) {
    ac_write_utf8(handle, text);
    ac_write_utf8(handle, L"\r\n");
}

static void ac_error_detail(DWORD code) {
    DWORD size;
    g_error_text[0] = L'\0';
    size = FormatMessageW(
        FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        NULL,
        code,
        0,
        g_error_text,
        (DWORD)(sizeof(g_error_text) / sizeof(g_error_text[0])),
        NULL
    );
    if (size == 0) ac_copy(g_error_text, 2048, L"Windows did not provide an error description.");
}

static void ac_fail(HANDLE report, const WCHAR *stage, DWORD code) {
    BOOL has_report = report != NULL && report != INVALID_HANDLE_VALUE;
    ac_error_detail(code);
    if (has_report) {
        ac_write_line(report, L"STATUS: FAILED");
        ac_write_utf8(report, L"STAGE: ");
        ac_write_line(report, stage);
        ac_write_utf8(report, L"WIN32_ERROR: ");
        g_message[0] = L'\0';
        ac_append_u32(g_message, AC_PATH_CAP + 2048, code);
        ac_write_line(report, g_message);
        ac_write_utf8(report, L"DETAIL: ");
        ac_write_line(report, g_error_text);
        ac_write_utf8(report, L"REPORT: ");
        ac_write_line(report, g_report_path);
        FlushFileBuffers(report);
    }

    ac_copy(g_message, AC_PATH_CAP + 2048, L"Accessible Chess не запустився.\r\n\r\nЕтап: ");
    ac_append(g_message, AC_PATH_CAP + 2048, stage);
    ac_append(g_message, AC_PATH_CAP + 2048, L"\r\nКод Windows: ");
    ac_append_u32(g_message, AC_PATH_CAP + 2048, code);
    if (has_report) {
        ac_append(g_message, AC_PATH_CAP + 2048, L"\r\n\r\nЗвіт: ");
        ac_append(g_message, AC_PATH_CAP + 2048, g_report_path);
    } else {
        ac_append(g_message, AC_PATH_CAP + 2048, L"\r\n\r\nЗвіт запуску не створено.");
    }
    MessageBoxW(NULL, g_message, L"Accessible Chess — помилка запуску", MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
    if (has_report) CloseHandle(report);
    ExitProcess(code == 0 ? 1 : code);
}

static BOOL ac_direct_directory(const WCHAR *path) {
    DWORD attrs = GetFileAttributesW(path);
    if (attrs == INVALID_FILE_ATTRIBUTES) return FALSE;
    if ((attrs & FILE_ATTRIBUTE_DIRECTORY) == 0) return FALSE;
    if ((attrs & FILE_ATTRIBUTE_REPARSE_POINT) != 0) return FALSE;
    return TRUE;
}

static BOOL ac_direct_file(const WCHAR *path) {
    DWORD attrs = GetFileAttributesW(path);
    if (attrs == INVALID_FILE_ATTRIBUTES) return FALSE;
    if ((attrs & FILE_ATTRIBUTE_DIRECTORY) != 0) return FALSE;
    if ((attrs & FILE_ATTRIBUTE_REPARSE_POINT) != 0) return FALSE;
    return TRUE;
}

static HANDLE ac_open_report(void) {
    HANDLE handle;
    DWORD written = 0;
    DWORD attempt;
    DWORD error = ERROR_SUCCESS;
    static const BYTE bom[3] = {0xEF, 0xBB, 0xBF};

    for (attempt = 0; attempt <= AC_REPORT_RETRY_COUNT; ++attempt) {
        handle = CreateFileW(
            g_report_path,
            GENERIC_WRITE,
            FILE_SHARE_READ,
            NULL,
            CREATE_ALWAYS,
            FILE_ATTRIBUTE_NORMAL,
            NULL
        );
        if (handle != INVALID_HANDLE_VALUE) {
            WriteFile(handle, bom, 3, &written, NULL);
            return handle;
        }
        error = GetLastError();
        if (error != ERROR_SHARING_VIOLATION || attempt == AC_REPORT_RETRY_COUNT) {
            SetLastError(error);
            return INVALID_HANDLE_VALUE;
        }
        Sleep(AC_REPORT_RETRY_MS);
    }
    SetLastError(error);
    return INVALID_HANDLE_VALUE;
}

static void ac_prepare_paths(void) {
    DWORD size = GetModuleFileNameW(NULL, g_module, AC_PATH_CAP);
    if (size == 0 || size >= AC_PATH_CAP) ExitProcess(ERROR_BUFFER_OVERFLOW);
    if (!ac_parent_dir(g_root, AC_PATH_CAP, g_module)) ExitProcess(ERROR_BAD_PATHNAME);
    if (!ac_path_join(g_app_dir, AC_PATH_CAP, g_root, L"App")) ExitProcess(ERROR_BUFFER_OVERFLOW);
    if (!ac_path_join(g_core, AC_PATH_CAP, g_app_dir, L"AccessibleChess.exe")) ExitProcess(ERROR_BUFFER_OVERFLOW);
    if (!ac_path_join(g_data, AC_PATH_CAP, g_root, L"data")) ExitProcess(ERROR_BUFFER_OVERFLOW);
    if (!ac_path_join(g_report_path, AC_PATH_CAP, g_root, L"launch-report.txt")) ExitProcess(ERROR_BUFFER_OVERFLOW);
}

void WINAPI wWinMainCRTStartup(void) {
    HANDLE report;
    DWORD error;
    DWORD wait_result;
    DWORD exit_code = STILL_ACTIVE;

    ac_prepare_paths();
    if (!ac_direct_directory(g_root)) {
        ac_fail(INVALID_HANDLE_VALUE, L"package-root validation", ERROR_DIRECTORY);
    }
    report = ac_open_report();
    if (report == INVALID_HANDLE_VALUE) {
        error = GetLastError();
        MessageBoxW(NULL, L"Accessible Chess cannot create launch-report.txt beside the program. Extract the ZIP to a writable folder and try again.", L"Accessible Chess — launch report error", MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
        ExitProcess(error == 0 ? 1 : error);
    }

    ac_write_line(report, L"ACCESSIBLE CHESS PORTABLE LAUNCH REPORT");
    ac_write_line(report, L"ENCODING: UTF-8");
    ac_write_line(report, L"HUMAN_TESTED: NO");
    ac_write_line(report, L"NVDA_VERIFIED: NO");
    ac_write_utf8(report, L"PACKAGE_ROOT: ");
    ac_write_line(report, g_root);
    ac_write_utf8(report, L"CORE: ");
    ac_write_line(report, g_core);
    ac_write_utf8(report, L"LOCALAPPDATA: ");
    ac_write_line(report, g_data);

    if (!ac_direct_directory(g_app_dir)) ac_fail(report, L"App directory validation", ERROR_PATH_NOT_FOUND);
    if (!ac_direct_file(g_core)) ac_fail(report, L"core executable validation", ERROR_FILE_NOT_FOUND);

    if (!CreateDirectoryW(g_data, NULL)) {
        error = GetLastError();
        if (error != ERROR_ALREADY_EXISTS) ac_fail(report, L"package-local data directory creation", error);
    }
    if (!ac_direct_directory(g_data)) ac_fail(report, L"package-local data directory validation", ERROR_DIRECTORY);

    if (!SetEnvironmentVariableW(L"LOCALAPPDATA", g_data)) {
        ac_fail(report, L"package-local LOCALAPPDATA binding", GetLastError());
    }
    ac_write_line(report, L"PREFLIGHT: PASS");

    g_command[0] = L'\0';
    if (!ac_append(g_command, AC_PATH_CAP * 2, L"\"") ||
        !ac_append(g_command, AC_PATH_CAP * 2, g_core) ||
        !ac_append(g_command, AC_PATH_CAP * 2, L"\"")) {
        ac_fail(report, L"child command construction", ERROR_BUFFER_OVERFLOW);
    }

    g_startup.cb = sizeof(g_startup);

    if (!CreateProcessW(
            g_core,
            g_command,
            NULL,
            NULL,
            FALSE,
            CREATE_UNICODE_ENVIRONMENT,
            NULL,
            g_app_dir,
            &g_startup,
            &g_process)) {
        ac_fail(report, L"core process creation", GetLastError());
    }
    CloseHandle(g_process.hThread);
    ac_write_line(report, L"PROCESS_CREATED: YES");
    FlushFileBuffers(report);

    wait_result = WaitForSingleObject(g_process.hProcess, AC_STARTUP_OBSERVE_MS);
    if (wait_result == WAIT_OBJECT_0) {
        if (!GetExitCodeProcess(g_process.hProcess, &exit_code)) {
            error = GetLastError();
            CloseHandle(g_process.hProcess);
            ac_fail(report, L"early child exit-code read", error);
        }
        ac_write_line(report, L"STATUS: FAILED_EARLY_EXIT");
        ac_write_utf8(report, L"CHILD_EXIT_CODE: ");
        g_message[0] = L'\0';
        ac_append_u32(g_message, AC_PATH_CAP + 2048, exit_code);
        ac_write_line(report, g_message);
        ac_write_utf8(report, L"CHILD_EXIT_REASON: ");
        ac_write_line(report, ac_child_exit_reason(exit_code));
        FlushFileBuffers(report);

        ac_copy(g_message, AC_PATH_CAP + 2048, L"Accessible Chess завершився одразу після запуску.\r\n\r\nКод: ");
        ac_append_u32(g_message, AC_PATH_CAP + 2048, exit_code);
        ac_append(g_message, AC_PATH_CAP + 2048, L"\r\nПричина: ");
        ac_append(g_message, AC_PATH_CAP + 2048, ac_child_exit_user_detail(exit_code));
        ac_append(g_message, AC_PATH_CAP + 2048, L"\r\nЗвіт: ");
        ac_append(g_message, AC_PATH_CAP + 2048, g_report_path);
        MessageBoxW(NULL, g_message, L"Accessible Chess — помилка запуску", MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
        CloseHandle(g_process.hProcess);
        CloseHandle(report);
        ExitProcess(exit_code == 0 ? 1 : exit_code);
    }

    if (wait_result == WAIT_FAILED) {
        error = GetLastError();
        CloseHandle(g_process.hProcess);
        ac_fail(report, L"startup observation", error);
    }

    ac_write_line(report, L"STATUS: CHILD_RUNNING_AFTER_STARTUP_OBSERVATION");
    ac_write_line(report, L"USER_WINDOW_PROVEN: NO");
    ac_write_line(report, L"USER_NVDA_PROVEN: NO");
    ac_write_line(report, L"NEXT: user verifies the exact packaged bytes with Windows/NVDA");
    FlushFileBuffers(report);
    CloseHandle(g_process.hProcess);
    CloseHandle(report);
    ExitProcess(0);
}
