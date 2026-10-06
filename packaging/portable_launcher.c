#define WIN32_LEAN_AND_MEAN
#include <windows.h>

/*
 * Accessible Chess portable launcher.
 *
 * Runtime contract:
 * - this executable lives at the extracted package root;
 * - the real product executable lives at App\AccessibleChess.exe;
 * - LOCALAPPDATA is redirected to package-root\data for the child only;
 * - one exact package root has one live child owner of package-local data;
 * - duplicate launcher invocations coalesce without starting another child;
 * - launch-report.txt is created beside this executable for blind-user support;
 * - startup succeeds only after the real child owns a responsive visible
 *   top-level "Accessible Chess" window; process/window liveness alone is not success;
 * - no shell, PowerShell, Python or installer is required at runtime.
 *
 * The release workflow links this file without the CRT. Keep this source on the
 * Win32 KERNEL32/USER32 surface so the launcher itself cannot gain a hidden
 * runtime dependency while solving a startup-dependency failure.
 */

#define AC_PATH_CAP 32768
#define AC_UTF8_CAP (AC_PATH_CAP * 4 + 4096)
#define AC_STARTUP_POLL_MS 100
#define AC_WINDOW_RESPONSE_PROBE_MS 100
#define AC_STARTUP_READY_STABILITY_MS 500
#define AC_STARTUP_WINDOW_TIMEOUT_MS 30000
#define AC_TIMEOUT_CLEANUP_WAIT_MS 5000
#define AC_REPORT_RETRY_MS 100
#define AC_REPORT_RETRY_COUNT 40
#define ACCESSIBILITY_HOST_INIT_EXIT_CODE 71
#define SAFE_LOCAL_SERVER_INIT_EXIT_CODE 72
#define RELEASE_UI_STARTUP_EXIT_CODE 73

static WCHAR g_module[AC_PATH_CAP];
static WCHAR g_root[AC_PATH_CAP];
static WCHAR g_app_dir[AC_PATH_CAP];
static WCHAR g_core[AC_PATH_CAP];
static WCHAR g_data[AC_PATH_CAP];
static WCHAR g_report_path[AC_PATH_CAP];
static WCHAR g_instance_lock_path[AC_PATH_CAP];
static WCHAR g_command[AC_PATH_CAP * 2];
static WCHAR g_message[AC_PATH_CAP + 2048];
static WCHAR g_error_text[2048];
static CHAR g_utf8[AC_UTF8_CAP];
static STARTUPINFOW g_startup;
static PROCESS_INFORMATION g_process;
static HANDLE g_instance_lock = INVALID_HANDLE_VALUE;

typedef struct AC_WINDOW_SEARCH {
    DWORD process_id;
    BOOL found;
} AC_WINDOW_SEARCH;

static SIZE_T ac_wlen(const WCHAR *value) {
    SIZE_T size = 0;
    if (value == NULL) return 0;
    while (value[size] != L'\0') ++size;
    return size;
}

static BOOL ac_equal(const WCHAR *left, const WCHAR *right) {
    SIZE_T index = 0;
    if (left == NULL || right == NULL) return FALSE;
    while (left[index] != L'\0' || right[index] != L'\0') {
        if (left[index] != right[index]) return FALSE;
        ++index;
    }
    return TRUE;
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
    if (code == RELEASE_UI_STARTUP_EXIT_CODE) return L"RELEASE_UI_STARTUP_FAILED";
    return L"UNKNOWN_EARLY_EXIT";
}

static const WCHAR *ac_child_exit_user_detail(DWORD code) {
    if (code == ACCESSIBILITY_HOST_INIT_EXIT_CODE) {
        return L"Не вдалося ініціалізувати доступний WebView2/WinForms інтерфейс.";
    }
    if (code == SAFE_LOCAL_SERVER_INIT_EXIT_CODE) {
        return L"Не вдалося ініціалізувати безпечний локальний сервер WebView2.";
    }
    if (code == RELEASE_UI_STARTUP_EXIT_CODE) {
        return L"Не вдалося запустити основний доступний інтерфейс Accessible Chess.";
    }
    return L"Невідома рання помилка основної програми.";
}

static void ac_close_child_process_handle(void) {
    if (g_process.hProcess == NULL || g_process.hProcess == INVALID_HANDLE_VALUE) return;
    CloseHandle(g_process.hProcess);
    g_process.hProcess = NULL;
}

static BOOL ac_retire_owned_child(DWORD code) {
    DWORD wait_result;
    DWORD stable_code = code == ERROR_SUCCESS ? ERROR_WRITE_FAULT : code;

    if (g_process.hProcess == NULL || g_process.hProcess == INVALID_HANDLE_VALUE) return TRUE;

    wait_result = WaitForSingleObject(g_process.hProcess, 0);
    if (wait_result == WAIT_OBJECT_0) return TRUE;

    if (!TerminateProcess(g_process.hProcess, stable_code)) {
        return WaitForSingleObject(g_process.hProcess, 0) == WAIT_OBJECT_0;
    }
    return WaitForSingleObject(
        g_process.hProcess,
        AC_TIMEOUT_CLEANUP_WAIT_MS
    ) == WAIT_OBJECT_0;
}

static void ac_report_write_fail(HANDLE report, DWORD code) {
    DWORD stable_code = code == ERROR_SUCCESS ? ERROR_WRITE_FAULT : code;
    BOOL child_stopped = ac_retire_owned_child(stable_code);
    if (report != NULL && report != INVALID_HANDLE_VALUE) CloseHandle(report);

    ac_copy(
        g_message,
        AC_PATH_CAP + 2048,
        L"Accessible Chess cannot fully write launch-report.txt.\r\n"
        L"The launcher is stopping because an incomplete report must not be treated as valid evidence.\r\n\r\n"
        L"Не вдалося повністю записати launch-report.txt.\r\n"
        L"Запуск засобу перевірки зупинено, бо неповний звіт не можна вважати достовірним.\r\n\r\n"
        L"Windows error / Код Windows: "
    );
    ac_append_u32(g_message, AC_PATH_CAP + 2048, stable_code);
    if (!child_stopped) {
        ac_append(
            g_message,
            AC_PATH_CAP + 2048,
            L"\r\n\r\nThe main Accessible Chess process may still be running. Do not start another copy until it is closed."
            L"\r\nОсновний процес Accessible Chess може ще працювати. Не запускайте другу копію, доки його не буде завершено."
        );
    }
    ac_close_child_process_handle();
    MessageBoxW(
        NULL,
        g_message,
        L"Accessible Chess — launch report write error",
        MB_OK | MB_ICONERROR | MB_SETFOREGROUND
    );
    ExitProcess(stable_code);
}

static void ac_write_utf8(HANDLE handle, const WCHAR *text) {
    int bytes;
    DWORD written = 0;
    DWORD error;
    if (handle == NULL || handle == INVALID_HANDLE_VALUE || text == NULL) {
        ac_report_write_fail(handle, ERROR_INVALID_PARAMETER);
    }
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
    if (bytes == 0) {
        error = GetLastError();
        ac_report_write_fail(handle, error == ERROR_SUCCESS ? ERROR_NO_UNICODE_TRANSLATION : error);
    }
    if (bytes == 1) return;
    if (!WriteFile(handle, g_utf8, (DWORD)(bytes - 1), &written, NULL)) {
        error = GetLastError();
        ac_report_write_fail(handle, error == ERROR_SUCCESS ? ERROR_WRITE_FAULT : error);
    }
    if (written != (DWORD)(bytes - 1)) {
        ac_report_write_fail(handle, ERROR_WRITE_FAULT);
    }
}

static void ac_write_line(HANDLE handle, const WCHAR *text) {
    ac_write_utf8(handle, text);
    ac_write_utf8(handle, L"\r\n");
}

static void ac_flush_report(HANDLE report) {
    DWORD error;
    if (report == NULL || report == INVALID_HANDLE_VALUE) {
        ac_report_write_fail(report, ERROR_INVALID_PARAMETER);
    }
    if (!FlushFileBuffers(report)) {
        error = GetLastError();
        ac_report_write_fail(report, error == ERROR_SUCCESS ? ERROR_WRITE_FAULT : error);
    }
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
    BOOL child_stopped = ac_retire_owned_child(code == 0 ? ERROR_GEN_FAILURE : code);
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
        ac_flush_report(report);
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
    if (!child_stopped) {
        ac_append(
            g_message,
            AC_PATH_CAP + 2048,
            L"\r\n\r\nОсновний процес може ще працювати. Не запускайте другу копію, доки його не буде завершено."
        );
    }
    ac_close_child_process_handle();
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

static HANDLE ac_open_direct_directory_guard(const WCHAR *path) {
    HANDLE handle;
    FILE_ATTRIBUTE_TAG_INFO tag_info;
    DWORD error;

    handle = CreateFileW(
        path,
        FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        NULL,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
        NULL
    );
    if (handle == INVALID_HANDLE_VALUE) return INVALID_HANDLE_VALUE;

    if (!GetFileInformationByHandleEx(
            handle,
            FileAttributeTagInfo,
            &tag_info,
            sizeof(tag_info))) {
        error = GetLastError();
        CloseHandle(handle);
        SetLastError(error);
        return INVALID_HANDLE_VALUE;
    }
    if ((tag_info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0 ||
        (tag_info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
        CloseHandle(handle);
        SetLastError(ERROR_CANT_ACCESS_FILE);
        return INVALID_HANDLE_VALUE;
    }
    return handle;
}

static HANDLE ac_open_direct_private_file(const WCHAR *path) {
    HANDLE handle;
    FILE_ATTRIBUTE_TAG_INFO tag_info;
    BY_HANDLE_FILE_INFORMATION file_info;
    DWORD error;

    handle = CreateFileW(
        path,
        FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
        NULL
    );
    if (handle == INVALID_HANDLE_VALUE) return INVALID_HANDLE_VALUE;

    if (!GetFileInformationByHandleEx(
            handle,
            FileAttributeTagInfo,
            &tag_info,
            sizeof(tag_info))) {
        error = GetLastError();
        CloseHandle(handle);
        SetLastError(error);
        return INVALID_HANDLE_VALUE;
    }
    if ((tag_info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0 ||
        (tag_info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
        CloseHandle(handle);
        SetLastError(ERROR_CANT_ACCESS_FILE);
        return INVALID_HANDLE_VALUE;
    }
    if (!GetFileInformationByHandle(handle, &file_info)) {
        error = GetLastError();
        CloseHandle(handle);
        SetLastError(error);
        return INVALID_HANDLE_VALUE;
    }
    if (file_info.nNumberOfLinks != 1) {
        CloseHandle(handle);
        SetLastError(ERROR_CANT_ACCESS_FILE);
        return INVALID_HANDLE_VALUE;
    }
    return handle;
}

static HANDLE ac_open_instance_lock(void) {
    HANDLE handle;
    FILE_ATTRIBUTE_TAG_INFO tag_info;
    BY_HANDLE_FILE_INFORMATION file_info;
    DWORD error;

    handle = CreateFileW(
        g_instance_lock_path,
        GENERIC_READ | GENERIC_WRITE,
        0,
        NULL,
        OPEN_ALWAYS,
        FILE_ATTRIBUTE_HIDDEN | FILE_FLAG_OPEN_REPARSE_POINT,
        NULL
    );
    if (handle == INVALID_HANDLE_VALUE) return INVALID_HANDLE_VALUE;

    if (!GetFileInformationByHandleEx(
            handle,
            FileAttributeTagInfo,
            &tag_info,
            sizeof(tag_info))) {
        error = GetLastError();
        CloseHandle(handle);
        SetLastError(error);
        return INVALID_HANDLE_VALUE;
    }
    if ((tag_info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
        CloseHandle(handle);
        SetLastError(ERROR_CANT_ACCESS_FILE);
        return INVALID_HANDLE_VALUE;
    }
    if (!GetFileInformationByHandle(handle, &file_info)) {
        error = GetLastError();
        CloseHandle(handle);
        SetLastError(error);
        return INVALID_HANDLE_VALUE;
    }
    if (file_info.nNumberOfLinks != 1) {
        CloseHandle(handle);
        SetLastError(ERROR_CANT_ACCESS_FILE);
        return INVALID_HANDLE_VALUE;
    }
    return handle;
}

static BOOL CALLBACK ac_find_ready_window(HWND window, LPARAM value) {
    AC_WINDOW_SEARCH *search = (AC_WINDOW_SEARCH *)value;
    DWORD process_id = 0;
    DWORD_PTR response = 0;
    WCHAR title[64];
    int size;

    if (search == NULL || !IsWindowVisible(window)) return TRUE;
    GetWindowThreadProcessId(window, &process_id);
    if (process_id != search->process_id) return TRUE;

    title[0] = L'\0';
    size = GetWindowTextW(window, title, (int)(sizeof(title) / sizeof(title[0])));
    if (size <= 0) return TRUE;
    if (!ac_equal(title, L"Accessible Chess")) return TRUE;

    if (SendMessageTimeoutW(
            window,
            WM_NULL,
            0,
            0,
            SMTO_ABORTIFHUNG | SMTO_BLOCK,
            AC_WINDOW_RESPONSE_PROBE_MS,
            &response) == 0) {
        return TRUE;
    }

    search->found = TRUE;
    return FALSE;
}

static BOOL ac_has_ready_window(DWORD process_id) {
    AC_WINDOW_SEARCH search;
    search.process_id = process_id;
    search.found = FALSE;
    EnumWindows(ac_find_ready_window, (LPARAM)&search);
    return search.found;
}

static HANDLE ac_open_report(void) {
    HANDLE handle;
    FILE_ATTRIBUTE_TAG_INFO tag_info;
    BY_HANDLE_FILE_INFORMATION file_info;
    LARGE_INTEGER zero;
    DWORD written = 0;
    DWORD attempt;
    DWORD error = ERROR_SUCCESS;
    static const BYTE bom[3] = {0xEF, 0xBB, 0xBF};

    zero.QuadPart = 0;
    for (attempt = 0; attempt <= AC_REPORT_RETRY_COUNT; ++attempt) {
        handle = CreateFileW(
            g_report_path,
            GENERIC_WRITE,
            FILE_SHARE_READ,
            NULL,
            OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
            NULL
        );
        if (handle != INVALID_HANDLE_VALUE) {
            if (!GetFileInformationByHandleEx(
                    handle,
                    FileAttributeTagInfo,
                    &tag_info,
                    sizeof(tag_info))) {
                error = GetLastError();
                CloseHandle(handle);
                SetLastError(error);
                return INVALID_HANDLE_VALUE;
            }
            if ((tag_info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
                CloseHandle(handle);
                SetLastError(ERROR_CANT_ACCESS_FILE);
                return INVALID_HANDLE_VALUE;
            }
            if (!GetFileInformationByHandle(handle, &file_info)) {
                error = GetLastError();
                CloseHandle(handle);
                SetLastError(error);
                return INVALID_HANDLE_VALUE;
            }
            if (file_info.nNumberOfLinks != 1) {
                CloseHandle(handle);
                SetLastError(ERROR_CANT_ACCESS_FILE);
                return INVALID_HANDLE_VALUE;
            }
            if (!SetFilePointerEx(handle, zero, NULL, FILE_BEGIN) || !SetEndOfFile(handle)) {
                error = GetLastError();
                CloseHandle(handle);
                SetLastError(error);
                return INVALID_HANDLE_VALUE;
            }
            if (!WriteFile(handle, bom, 3, &written, NULL) || written != 3) {
                error = GetLastError();
                if (error == ERROR_SUCCESS) error = ERROR_WRITE_FAULT;
                CloseHandle(handle);
                SetLastError(error);
                return INVALID_HANDLE_VALUE;
            }
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
    if (!ac_path_join(g_instance_lock_path, AC_PATH_CAP, g_root, L".accessible-chess-instance.lock")) ExitProcess(ERROR_BUFFER_OVERFLOW);
}

static void ac_fail_startup_timeout(HANDLE report) {
    DWORD cleanup_error = ERROR_SUCCESS;
    DWORD cleanup_wait = WAIT_FAILED;
    BOOL child_stopped = FALSE;

    /*
     * A timed-out child still owns the package-local single-instance lock and
     * data-directory guard.  Retire it before any fallible report write so a
     * report failure cannot strand an invisible process that blocks retry.
     */
    if (!TerminateProcess(g_process.hProcess, ERROR_TIMEOUT)) {
        cleanup_error = GetLastError();
        cleanup_wait = WaitForSingleObject(g_process.hProcess, 0);
        if (cleanup_wait == WAIT_OBJECT_0) {
            child_stopped = TRUE;
            cleanup_error = ERROR_SUCCESS;
        }
    } else {
        cleanup_wait = WaitForSingleObject(g_process.hProcess, AC_TIMEOUT_CLEANUP_WAIT_MS);
        if (cleanup_wait == WAIT_OBJECT_0) {
            child_stopped = TRUE;
        } else if (cleanup_wait == WAIT_FAILED) {
            cleanup_error = GetLastError();
        } else {
            cleanup_error = ERROR_TIMEOUT;
        }
    }

    ac_write_line(report, L"STATUS: FAILED_STARTUP_TIMEOUT");
    ac_write_line(report, L"USER_WINDOW_PROVEN: NO");
    ac_write_line(report, L"USER_NVDA_PROVEN: NO");
    if (child_stopped) {
        ac_write_line(report, L"TIMEOUT_CHILD_CLEANUP: PASS");
        ac_write_line(report, L"CHILD_LEFT_RUNNING: NO");
        ac_write_line(report, L"NEXT: keep launch-report.txt and retry once from the extracted package root");
    } else {
        ac_write_line(report, L"TIMEOUT_CHILD_CLEANUP: FAILED");
        ac_write_utf8(report, L"TIMEOUT_CHILD_CLEANUP_WIN32_ERROR: ");
        g_message[0] = L'\0';
        ac_append_u32(
            g_message,
            AC_PATH_CAP + 2048,
            cleanup_error == ERROR_SUCCESS ? ERROR_GEN_FAILURE : cleanup_error
        );
        ac_write_line(report, g_message);
        ac_write_line(report, L"CHILD_LEFT_RUNNING: YES");
        ac_write_line(report, L"NEXT: keep launch-report.txt; the timed-out process could not be stopped automatically");
    }
    ac_write_line(report, L"DETAIL: Accessible Chess did not expose a stable responsive visible application window before the startup deadline.");
    ac_flush_report(report);

    if (child_stopped) {
        ac_copy(
            g_message,
            AC_PATH_CAP + 2048,
            L"Accessible Chess не підтвердив готовність вікна протягом 30 секунд.\r\n\r\n"
            L"Завислий процес автоматично завершено. Можна повторити запуск з цієї папки.\r\n"
            L"Збережіть звіт:\r\n"
        );
    } else {
        ac_copy(
            g_message,
            AC_PATH_CAP + 2048,
            L"Accessible Chess не підтвердив готовність вікна протягом 30 секунд.\r\n\r\n"
            L"Автоматично завершити завислий процес не вдалося. Не запускайте другу копію, доки процес не буде завершено.\r\n"
            L"Збережіть звіт:\r\n"
        );
    }
    ac_append(g_message, AC_PATH_CAP + 2048, g_report_path);
    MessageBoxW(NULL, g_message, L"Accessible Chess — вікно не готове", MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
    ac_close_child_process_handle();
    CloseHandle(report);
    ExitProcess(ERROR_TIMEOUT);
}

void WINAPI wWinMainCRTStartup(void) {
    HANDLE report;
    HANDLE root_guard = INVALID_HANDLE_VALUE;
    HANDLE app_guard = INVALID_HANDLE_VALUE;
    HANDLE core_guard = INVALID_HANDLE_VALUE;
    HANDLE data_guard = INVALID_HANDLE_VALUE;
    HANDLE child_instance_lock = NULL;
    HANDLE child_root_guard = NULL;
    HANDLE child_app_guard = NULL;
    HANDLE child_data_guard = NULL;
    DWORD error;
    DWORD wait_result;
    DWORD exit_code = STILL_ACTIVE;
    DWORD resume_result;
    ULONGLONG startup_started;
    ULONGLONG ready_started = 0;
    ULONGLONG now;
    BOOL ready_tracking = FALSE;
    BOOL window_ready;

    ac_prepare_paths();
    if (!ac_direct_directory(g_root)) {
        ac_fail(INVALID_HANDLE_VALUE, L"package-root validation", ERROR_DIRECTORY);
    }
    root_guard = ac_open_direct_directory_guard(g_root);
    if (root_guard == INVALID_HANDLE_VALUE) {
        error = GetLastError();
        ac_fail(
            INVALID_HANDLE_VALUE,
            L"package-root directory guard",
            error == ERROR_SUCCESS ? ERROR_CANT_ACCESS_FILE : error
        );
    }

    g_instance_lock = ac_open_instance_lock();
    if (g_instance_lock == INVALID_HANDLE_VALUE) {
        error = GetLastError();
        if (error == ERROR_SHARING_VIOLATION || error == ERROR_LOCK_VIOLATION) {
            ExitProcess(0);
        }
        ac_fail(INVALID_HANDLE_VALUE, L"package-local single-instance guard", error);
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
    ac_write_line(report, L"PACKAGE_DATA_OWNER: SINGLE_INSTANCE_GUARD_ACTIVE");
    ac_write_line(report, L"PACKAGE_ROOT_GUARD: DIRECT_DIRECTORY_HANDLE_READY");
    ac_write_utf8(report, L"PACKAGE_ROOT: ");
    ac_write_line(report, g_root);
    ac_write_utf8(report, L"CORE: ");
    ac_write_line(report, g_core);
    ac_write_utf8(report, L"LOCALAPPDATA: ");
    ac_write_line(report, g_data);

    if (!ac_direct_directory(g_app_dir)) ac_fail(report, L"App directory validation", ERROR_PATH_NOT_FOUND);
    app_guard = ac_open_direct_directory_guard(g_app_dir);
    if (app_guard == INVALID_HANDLE_VALUE) {
        error = GetLastError();
        ac_fail(
            report,
            L"App runtime directory guard",
            error == ERROR_SUCCESS ? ERROR_CANT_ACCESS_FILE : error
        );
    }
    ac_write_line(report, L"APP_RUNTIME_GUARD: DIRECT_DIRECTORY_HANDLE_READY");
    core_guard = ac_open_direct_private_file(g_core);
    if (core_guard == INVALID_HANDLE_VALUE) {
        error = GetLastError();
        ac_fail(report, L"core executable validation", error == ERROR_SUCCESS ? ERROR_FILE_NOT_FOUND : error);
    }

    if (!CreateDirectoryW(g_data, NULL)) {
        error = GetLastError();
        if (error != ERROR_ALREADY_EXISTS) ac_fail(report, L"package-local data directory creation", error);
    }
    if (!ac_direct_directory(g_data)) ac_fail(report, L"package-local data directory validation", ERROR_DIRECTORY);
    data_guard = ac_open_direct_directory_guard(g_data);
    if (data_guard == INVALID_HANDLE_VALUE) {
        error = GetLastError();
        ac_fail(report, L"package-local data directory guard", error == ERROR_SUCCESS ? ERROR_CANT_ACCESS_FILE : error);
    }
    ac_write_line(report, L"PACKAGE_DATA_GUARD: DIRECT_DIRECTORY_HANDLE_READY");

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
            CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED,
            NULL,
            g_app_dir,
            &g_startup,
            &g_process)) {
        error = GetLastError();
        CloseHandle(core_guard);
        ac_fail(report, L"core process creation", error);
    }
    CloseHandle(core_guard);
    core_guard = INVALID_HANDLE_VALUE;

    if (!DuplicateHandle(
            GetCurrentProcess(),
            g_instance_lock,
            g_process.hProcess,
            &child_instance_lock,
            0,
            FALSE,
            DUPLICATE_SAME_ACCESS)) {
        error = GetLastError();
        CloseHandle(g_process.hThread);
        ac_fail(report, L"package-local data ownership transfer", error);
    }

    if (!DuplicateHandle(
            GetCurrentProcess(),
            root_guard,
            g_process.hProcess,
            &child_root_guard,
            0,
            FALSE,
            DUPLICATE_SAME_ACCESS)) {
        error = GetLastError();
        CloseHandle(g_process.hThread);
        ac_fail(report, L"package-root directory guard transfer", error);
    }

    if (!DuplicateHandle(
            GetCurrentProcess(),
            app_guard,
            g_process.hProcess,
            &child_app_guard,
            0,
            FALSE,
            DUPLICATE_SAME_ACCESS)) {
        error = GetLastError();
        CloseHandle(g_process.hThread);
        ac_fail(report, L"App runtime directory guard transfer", error);
    }

    if (!DuplicateHandle(
            GetCurrentProcess(),
            data_guard,
            g_process.hProcess,
            &child_data_guard,
            0,
            FALSE,
            DUPLICATE_SAME_ACCESS)) {
        error = GetLastError();
        CloseHandle(g_process.hThread);
        ac_fail(report, L"package-local data directory guard transfer", error);
    }

    resume_result = ResumeThread(g_process.hThread);
    if (resume_result == (DWORD)-1) {
        error = GetLastError();
        CloseHandle(g_process.hThread);
        ac_fail(report, L"core process resume", error);
    }
    CloseHandle(g_process.hThread);
    CloseHandle(g_instance_lock);
    g_instance_lock = INVALID_HANDLE_VALUE;
    CloseHandle(root_guard);
    root_guard = INVALID_HANDLE_VALUE;
    CloseHandle(app_guard);
    app_guard = INVALID_HANDLE_VALUE;
    CloseHandle(data_guard);
    data_guard = INVALID_HANDLE_VALUE;
    ac_write_line(report, L"PACKAGE_ROOT_GUARD: TRANSFERRED_TO_CHILD");
    ac_write_line(report, L"APP_RUNTIME_GUARD: TRANSFERRED_TO_CHILD");
    ac_write_line(report, L"PACKAGE_DATA_GUARD: TRANSFERRED_TO_CHILD");

    ac_write_line(report, L"PROCESS_CREATED: YES");
    ac_write_utf8(report, L"CHILD_PROCESS_ID: ");
    g_message[0] = L'\0';
    if (!ac_append_u32(g_message, AC_PATH_CAP + 2048, g_process.dwProcessId)) {
        ac_fail(report, L"child process identity report", ERROR_BUFFER_OVERFLOW);
    }
    ac_write_line(report, g_message);
    ac_write_line(report, L"STARTUP_READINESS: waiting for stable responsive visible Accessible Chess window");
    ac_flush_report(report);
    startup_started = GetTickCount64();

    for (;;) {
        wait_result = WaitForSingleObject(g_process.hProcess, AC_STARTUP_POLL_MS);
        if (wait_result == WAIT_OBJECT_0) {
            if (!GetExitCodeProcess(g_process.hProcess, &exit_code)) {
                error = GetLastError();
                ac_fail(report, L"early child exit-code read", error);
            }
            ac_write_line(report, L"STATUS: FAILED_EARLY_EXIT");
            ac_write_utf8(report, L"CHILD_EXIT_CODE: ");
            g_message[0] = L'\0';
            ac_append_u32(g_message, AC_PATH_CAP + 2048, exit_code);
            ac_write_line(report, g_message);
            ac_write_utf8(report, L"CHILD_EXIT_REASON: ");
            ac_write_line(report, ac_child_exit_reason(exit_code));
            ac_write_line(report, L"USER_WINDOW_PROVEN: NO");
            ac_flush_report(report);

            ac_copy(g_message, AC_PATH_CAP + 2048, L"Accessible Chess завершився до появи робочого вікна.\r\n\r\nКод: ");
            ac_append_u32(g_message, AC_PATH_CAP + 2048, exit_code);
            ac_append(g_message, AC_PATH_CAP + 2048, L"\r\nПричина: ");
            ac_append(g_message, AC_PATH_CAP + 2048, ac_child_exit_user_detail(exit_code));
            ac_append(g_message, AC_PATH_CAP + 2048, L"\r\nЗвіт: ");
            ac_append(g_message, AC_PATH_CAP + 2048, g_report_path);
            MessageBoxW(NULL, g_message, L"Accessible Chess — помилка запуску", MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
            ac_close_child_process_handle();
            CloseHandle(report);
            ExitProcess(exit_code == 0 ? 1 : exit_code);
        }

        if (wait_result == WAIT_FAILED) {
            error = GetLastError();
            ac_fail(report, L"startup window observation", error);
        }

        if (wait_result != WAIT_TIMEOUT) {
            ac_fail(report, L"startup window observation", ERROR_INVALID_DATA);
        }

        window_ready = ac_has_ready_window(g_process.dwProcessId);
        now = GetTickCount64();
        if (now - startup_started >= AC_STARTUP_WINDOW_TIMEOUT_MS) {
            ac_fail_startup_timeout(report);
        }

        if (window_ready) {
            if (!ready_tracking) {
                ready_started = now;
                ready_tracking = TRUE;
            } else if (now - ready_started >= AC_STARTUP_READY_STABILITY_MS) {
                break;
            }
        } else {
            ready_tracking = FALSE;
            ready_started = 0;
        }
    }

    ac_write_line(report, L"STATUS: STARTUP_WINDOW_READY");
    ac_write_line(report, L"USER_WINDOW_PROVEN: YES");
    ac_write_line(report, L"USER_NVDA_PROVEN: NO");
    ac_write_line(report, L"NEXT: user verifies keyboard and NVDA behavior on these exact packaged bytes");
    ac_flush_report(report);
    ac_close_child_process_handle();
    CloseHandle(report);
    ExitProcess(0);
}