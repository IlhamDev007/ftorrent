"""Ftorrent, a local Windows torrent downloader.
No Google Drive integration. Download only content you are authorized to obtain.
Install: python -m pip install libtorrent
"""
import logging
import os
from pathlib import Path
from shutil import get_terminal_size
import sys
import time
try:
    import libtorrent as lt
except ImportError:
    sys.exit('Install libtorrent: python -m pip install libtorrent')
ROOT = Path.home() / 'Downloads' / 'Torrents'
STATE = ROOT / '.torrent_state'
LOG = logging.getLogger('torrent_app')
APP_NAME = 'Ftorrent'
MAIN_MENU = '[1] Upload File  [2] Magnet Link  [3] Start Download  [4] Exit'
RESULT_MENU = '[1] Open File Location  [2] Add New Download  [3] Exit'
COLORS = {'heading': '1;94', 'accent': '96', 'success': '32', 'warning': '1;33', 'error': '1;31'}
COLOR_ENABLED = False
LIVE_TERMINAL = False


def supports_ansi(stream):
    if not stream.isatty() or os.environ.get('TERM') == 'dumb':
        return False
    if os.name != 'nt':
        return True

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.windll.kernel32
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
    mode = wintypes.DWORD()
    enable_virtual_terminal_processing = 0x0004
    return bool(kernel.GetConsoleMode(handle, ctypes.byref(mode))
                and kernel.SetConsoleMode(handle, mode.value | enable_virtual_terminal_processing))


def color(text, tone, enabled=None):
    if enabled is None:
        enabled = COLOR_ENABLED
    return f'\x1b[{COLORS[tone]}m{text}\x1b[0m' if enabled else text


class TerminalLogFormatter(logging.Formatter):
    def __init__(self, stream):
        super().__init__('%(asctime)s  %(levelname)-7s  %(message)s', datefmt='%H:%M:%S')
        self.use_color = 'NO_COLOR' not in os.environ and supports_ansi(stream)

    def format(self, record):
        message = super().format(record)
        if record.levelno >= logging.WARNING:
            tone = 'error' if record.levelno >= logging.ERROR else 'warning'
            return color(message, tone, self.use_color)
        return message


def heading(title):
    print('\n' + color(title, 'heading'))


def menu(title, *options):
    heading(title)
    for index, option in enumerate(options, 1):
        print(f'  {index}. {option}')


def choose_file():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        try:
            return filedialog.askopenfilename(title='Choose a torrent file', filetypes=[('Torrent files', '*.torrent')])
        finally:
            root.destroy()
    except Exception:
        print(color('The file picker could not open.', 'warning'))
        return ''


def get_source():
    params = None
    heading(MAIN_MENU)
    while True:
        choice = input('Choose [1-4]: ').strip()
        if choice == '1':
            source = choose_file()
            if source:
                try:
                    params = lt.load_torrent_file(source)
                    print(color(f'{symbol("✓")} Ready to start: {Path(source).name}', 'success'))
                except (OSError, RuntimeError, ValueError):
                    print(color('Choose a readable .torrent file.', 'warning'))
        elif choice == '2':
            uri = input('Magnet link: ').strip()
            if uri:
                try:
                    params = lt.parse_magnet_uri(uri)
                    print(color(f'{symbol("✓")} Magnet link ready to start.', 'success'))
                except (RuntimeError, ValueError):
                    print(color('Enter a valid magnet link.', 'warning'))
        elif choice == '3':
            if params is not None:
                return params
            print(color('Add at least one torrent first.', 'warning'))
        elif choice == '4':
            return None
        else:
            print(color('Invalid choice.', 'warning'))


def hash_for(params):
    hashes = params.ti.info_hashes() if params.ti is not None else params.info_hashes
    return str(hashes.get_best())


def add_source(session, params):
    params.save_path = str(ROOT)
    key = hash_for(params)
    if key:
        checkpoint = STATE / (key + '.fastresume')
        if checkpoint.exists():
            try:
                resumed = lt.read_resume_data(checkpoint.read_bytes())
                resumed.save_path = str(ROOT)
                if hash_for(resumed) != key:
                    raise ValueError('Checkpoint does not match torrent')
                if params.ti is not None:
                    resumed.ti = params.ti
                if params.trackers:
                    resumed.trackers = params.trackers
                    resumed.tracker_tiers = params.tracker_tiers
                params = resumed
            except Exception as exc:
                LOG.debug('Ignoring unusable checkpoint: %s', exc)
    flags = lt.torrent_flags
    params.flags |= flags.upload_mode
    params.flags &= ~(flags.auto_managed | flags.paused)
    params.file_priorities = []
    params.piece_priorities = []
    return session.add_torrent(params)


def process_alerts(session):
    checkpoint_finished = False
    for alert in session.pop_alerts():
        if isinstance(alert, lt.save_resume_data_alert):
            checkpoint_finished = True
            try:
                key = str(alert.handle.info_hashes().get_best())
                checkpoint = STATE / (key + '.fastresume')
                temporary = checkpoint.with_suffix('.tmp')
                temporary.write_bytes(bytes(lt.write_resume_data_buf(alert.params)))
                temporary.replace(checkpoint)
            except Exception as exc:
                LOG.warning('Checkpoint write failed: %s', exc)
        elif isinstance(alert, lt.save_resume_data_failed_alert):
            checkpoint_finished = True
            LOG.warning('Checkpoint request failed: %s', alert.message())
    return checkpoint_finished


def request_checkpoint(handle):
    try:
        handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
        return True
    except RuntimeError as exc:
        LOG.warning('Could not request checkpoint: %s', exc)
        return False


def error_message(status):
    err = getattr(status, 'errc', None)
    if err is None:
        return None
    try:
        if int(err.value()) == 0:
            return None
    except (AttributeError, TypeError, ValueError):
        pass
    message = err.message()
    if message.lower() in ('success', 'the operation completed successfully', 'no error'):
        return None
    return message




def size_label(n):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if n < 1024 or unit == 'TiB':
            return f'{n:.1f} {unit}'
        n /= 1024


def file_entries(info):
    fs = info.layout()
    return [(i, Path(fs.file_path(i)), fs.file_size(i)) for i in range(fs.num_files())
            if not fs.file_flags(i) & lt.file_flags_t.flag_pad_file]


def print_tree(info):
    """Display each directory once and map menu numbers to torrent indexes."""
    entries = file_entries(info)
    folders = {}
    folder_indexes = {}
    files = {}
    root = Path('.')
    torrent_name = info.name()
    if entries and all(len(path.parts) > 1 and path.parts[0] == torrent_name
                       for _, path, _ in entries):
        root = Path(torrent_name)

    for index, path, size in entries:
        files.setdefault(path.parent, []).append((index, path.name, size))
        for parent in path.parents:
            if parent == root:
                break
            folders.setdefault(parent.parent, set()).add(parent)
            folder_indexes.setdefault(parent, set()).add(index)

    heading(f'{torrent_name}  |  {len(entries)} files')
    options = {0: {index for index, _, _ in entries}}
    print('  [0] All')
    pending = [(root, 1)]
    while pending:
        folder, depth = pending.pop()
        indent = '  ' * depth
        if folder != root:
            number = len(options)
            options[number] = folder_indexes[folder]
            print(indent[:-2] + color(f'[{number}] {folder.name}/', 'heading'))
        for index, name, size in files.get(folder, ()):
            number = len(options)
            options[number] = {index}
            print(f'{indent}[{number}] {name}  {size_label(size)}')
        children = sorted(folders.get(folder, ()), key=lambda path: path.name.casefold(), reverse=True)
        pending.extend((child, depth + 1) for child in children)
    return options


def choose_selection(info, handle):
    options = print_tree(info)
    print('\n  Select by number, e.g. 1,3-5  |  [B] Back  |  [?] Inspect')
    while True:
        raw = input('Download selection [0]: ').strip().lower()
        if raw in ('b', 'none'):
            return set()
        if raw == '?':
            inspect_files(handle, options[0])
            continue
        try:
            chosen = set()
            for token in (raw or '0').split(','):
                first, separator, last = token.partition('-')
                start = int(first)
                end = int(last) if separator else start
                if not 0 <= start <= end < len(options):
                    raise ValueError
                for number in range(start, end + 1):
                    chosen.update(options[number])
            return chosen
        except ValueError:
            print(color('Choose a number or range from the list.', 'warning'))


def selected_paths(handle, selected):
    try:
        fs = handle.torrent_file().layout()
        paths = []
        for i in selected:
            path = (ROOT / fs.file_path(i)).resolve()
            if path.is_relative_to(ROOT.resolve()) and path.is_file():
                paths.append(path)
        return paths
    except Exception as exc:
        LOG.warning('Could not enumerate downloaded files: %s', exc)
        return []


def availability_report(handle, selected):
    """Best-effort peer piece coverage, not guaranteed remote availability."""
    info = handle.torrent_file()
    fs = info.layout()
    try:
        counts = list(handle.piece_availability())
    except Exception as exc:
        print(color(f'Peer availability information unavailable: {exc}', 'warning'))
        return
    heading('Peer piece coverage  |  Connected peers')
    for i in sorted(selected):
        size = fs.file_size(i)
        if not size:
            print(f'  100%  {fs.file_path(i)}')
            continue
        offset = fs.file_offset(i)
        first = offset // info.piece_length()
        last = (offset + size - 1) // info.piece_length()
        window = counts[first:last+1]
        covered = sum(1 for n in window if n > 0)
        ratio = covered / len(window) if window else 0
        label = 'available' if ratio == 1 else ('partially available' if ratio else 'unavailable from connected peers')
        tone = 'success' if ratio == 1 else 'warning'
        print(f'  {ratio:>4.0%}  {color(label, tone)}  {fs.file_path(i)}')
    print('Shared boundary pieces and peers changing may affect accuracy. This is not a promise of completion.')


def preview_local_file(path):
    """Only inspect existing local bytes; never pretend metadata contains file content."""
    if not path.is_file():
        print(color('No local file data exists yet.', 'warning'))
        return
    menu(f'Local file  |  {path}  |  {size_label(path.stat().st_size)}',
         'Open in default application', 'Show first 512 bytes (hex)', 'Back')
    choice = input('Choose: ').strip()
    if choice == '1':
        os.startfile(str(path))
    elif choice == '2':
        with path.open('rb') as f:
            print(f.read(512).hex(' ', 16))
    print('Caution: partial files may be incomplete or invalid; do not trust their contents until verified.')


def inspect_files(handle, selected):
    info = handle.torrent_file()
    entries = file_entries(info)
    menu('Inspect torrent', 'Show folder tree', 'Preview local file', 'Peer availability', 'Back to selection')
    while True:
        choice = input('Choose [1-4, Enter to go back]: ').strip()
        if choice == '1': print_tree(info)
        elif choice == '2':
            try:
                for number, (_, path, _) in enumerate(entries, 1):
                    print(f'  [{number}] {path.name}')
                index = int(input('File number: ')) - 1
                if not 0 <= index < len(entries): raise ValueError()
                path = (ROOT / entries[index][1]).resolve()
                if not path.is_relative_to(ROOT.resolve()):
                    raise ValueError()
                preview_local_file(path)
            except ValueError: print(color('Invalid file number.', 'warning'))
        elif choice == '3': availability_report(handle, selected)
        elif choice in ('', '4'): return


def get_info_for_handle(handle, timeout=90):
    if info := handle.torrent_file():
        return info
    print('Waiting for torrent metadata...')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if info := handle.torrent_file():
            return info
        if error := error_message(handle.status()):
            raise RuntimeError(error)
        time.sleep(0.25)
    raise TimeoutError('Metadata timed out. Try a .torrent file or retry when peers are online.')


def apply_selection(handle, info, selected):
    priorities = [4 if index in selected else 0 for index in range(info.num_files())]
    handle.prioritize_files(priorities)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = handle.status()
        if error := error_message(status):
            raise RuntimeError(error)
        if status.is_seeding or list(handle.get_file_priorities()) == priorities:
            handle.unset_flags(lt.torrent_flags.upload_mode)
            return
        time.sleep(0.05)
    raise RuntimeError('File selection could not be applied. Try again.')


def symbol(character):
    try:
        character.encode(sys.stdout.encoding or 'ascii')
    except UnicodeEncodeError:
        return '*'
    return character


def show_progress(status, received, total, finished, redraw):
    width = max(1, min(70, get_terminal_size().columns - 1))
    ratio = min(1, received / total) if total else float(finished)
    bar_width = min(30, max(1, width - 12))
    filled = int(bar_width * ratio)
    bar = '#' * filled + '-' * (bar_width - filled)
    rate = status.download_payload_rate
    state = 'Complete' if finished else 'Downloading' if rate else 'Waiting / checking'
    lines = (
        f'{symbol(chr(0x26A1))} {status.name}',
        f'[{bar}] {ratio:6.1%}',
        f'{size_label(received)} / {size_label(total)}   {size_label(rate)}/s   Peers {status.num_peers}',
        state,
    )
    if redraw:
        print('\x1b[4A', end='')
    for line, tone in zip(lines, ('heading', 'heading', 'accent', 'success' if finished else 'accent')):
        prefix = '\x1b[2K\r' if LIVE_TERMINAL else ''
        print(prefix + color(line[:width], tone))
    sys.stdout.flush()


def monitor_download(session, handle, sizes):
    total = sum(sizes.values())
    last_draw = float('-inf')
    last_checkpoint = last_progress = time.monotonic()
    last_bytes = -1
    checkpoint_pending = False
    try:
        while True:
            status = handle.status()
            if error := error_message(status):
                raise RuntimeError(error)
            progress = handle.file_progress()
            received = sum(min(progress[index], size) for index, size in sizes.items())
            finished = all(progress[index] >= size for index, size in sizes.items())
            now = time.monotonic()
            if finished or now - last_draw >= (1 if LIVE_TERMINAL else 30):
                show_progress(status, received, total, finished,
                              LIVE_TERMINAL and last_draw != float('-inf'))
                last_draw = now
            if finished:
                return
            if received > last_bytes:
                last_bytes, last_progress = received, now
            if now - last_progress >= 600:
                handle.force_reannounce()
                last_progress = now
            if process_alerts(session):
                checkpoint_pending = False
            if not checkpoint_pending and now - last_checkpoint >= 120:
                checkpoint_pending = request_checkpoint(handle)
                last_checkpoint = now
            time.sleep(0.25)
    finally:
        if checkpoint_pending:
            wait_for_checkpoint(session)
        if request_checkpoint(handle):
            wait_for_checkpoint(session)


def wait_for_checkpoint(session):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process_alerts(session):
            return
        time.sleep(0.05)
    LOG.warning('Download checkpoint could not be confirmed.')


def run_download(params):
    ROOT.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    session = lt.session({'listen_interfaces': '0.0.0.0:6881'})
    handle = add_source(session, params)
    try:
        info = get_info_for_handle(handle)
        selected = choose_selection(info, handle)
        if not selected:
            return None
        apply_selection(handle, info, selected)
        layout = info.layout()
        sizes = {index: layout.file_size(index) for index in selected}
        print()
        monitor_download(session, handle, sizes)
        paths = selected_paths(handle, selected)
        return Path(os.path.commonpath([path.parent for path in paths])) if paths else ROOT
    finally:
        session.remove_torrent(handle)


def show_banner():
    wordmark = r'''
    _____ _                             _
   |  ___| |_ ___  _ __ _ __ ___ _ __ | |_
   | |_  | __/ _ \| '__| '__/ _ \ '_ \| __|
   |  _| | || (_) | |  | | |  __/ | | | |_
   |_|    \__\___/|_|  |_|  \___|_| |_|\__|
'''.strip('\n')
    bolt = r'''
            ______
           / ____/
          / /__
         /___  /
            / /
           / /
          /_/
'''.strip('\n')
    # Reveal the ASCII artwork a line at a time on an interactive terminal.
    for artwork, tone in ((wordmark, 'heading'), (bolt, 'accent')):
        for line in artwork.splitlines():
            print(color(line, tone), flush=True)
            if LIVE_TERMINAL:
                time.sleep(0.035)
    print(color(f'  {symbol(chr(0x26A1))} {APP_NAME}  |  Windows torrent downloader', 'heading'))


def completion_menu(location):
    print('\n' + color(f'{symbol(chr(0x2705))} Download complete', 'success'))
    print(f'  Saved to  {location}')
    heading(RESULT_MENU)
    while True:
        choice = input('Choose [1-3]: ').strip()
        if choice == '1':
            try:
                os.startfile(str(location))
            except OSError:
                print(color('The folder could not be opened.', 'warning'))
        elif choice == '2':
            return True
        elif choice == '3':
            return False
        else:
            print(color('Choose 1, 2, or 3.', 'warning'))


def main():
    global COLOR_ENABLED, LIVE_TERMINAL
    LIVE_TERMINAL = supports_ansi(sys.stdout)
    COLOR_ENABLED = LIVE_TERMINAL and 'NO_COLOR' not in os.environ
    handler = logging.StreamHandler()
    handler.setFormatter(TerminalLogFormatter(handler.stream))
    logging.basicConfig(level=logging.WARNING, handlers=[handler])
    show_banner()
    while (params := get_source()) is not None:
        try:
            location = run_download(params)
        except KeyboardInterrupt:
            print('\n' + color('Download stopped. Returning to the main menu.', 'warning'))
            continue
        except (OSError, RuntimeError, ValueError) as exc:
            print('\n' + color(f'Download could not continue: {exc}', 'error'))
            continue
        if location is not None and not completion_menu(location):
            break


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print()
