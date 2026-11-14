"""
GRUB's menu and its two choices, for the task reboot-to on Linux (--via=grub) - plain functions without cMeta, so the
offline tests import this file alone:

  once     grub-reboot <entry>: GRUB's next_entry - the header of grub.cfg starts it at the next boot whatever
           GRUB_DEFAULT is, then forgets it
  always   grub-set-default <entry>: GRUB's saved_entry, which counts only with GRUB_DEFAULT=saved in /etc/default/grub
           (set once, then update-grub)

An entry is named by its id ($menuentry_id_option: osprober-efi-A070-BC84, gnulinux-simple-<uuid>), stable when
kernels come and go, never by its position.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import re

CFG_PATHS = ('/boot/grub/grub.cfg', '/boot/grub2/grub.cfg', '/boot/efi/EFI/fedora/grub.cfg')
DEFAULTS = '/etc/default/grub'

ENTRY_RE = re.compile(r"""^\s*(menuentry|submenu)\s+(?:'([^']*)'|"([^"]*)")(.*?)\{?\s*$""")
ID_RE = re.compile(r"""(?:\$menuentry_id_option|--id)\s+(?:'([^']*)'|"([^"]*)"|(\S+))""")
CLASS_RE = re.compile(r'--class\s+(\S+)')


def cfg_path():
    return next((p for p in CFG_PATHS if os.path.isfile(p)), None)


def env_path(cfg):
    return os.path.join(os.path.dirname(cfg), 'grubenv') if cfg else None


def system_of(title, classes):
    low = title.lower()
    if 'windows' in classes or low.startswith('windows'):
        return 'windows'
    if 'memtest' in classes or 'firmware' in low or 'memory test' in low:
        return ''
    if {'gnu-linux', 'gnu', 'ubuntu', 'debian', 'fedora', 'linux'} & set(classes) or 'linux' in low or 'ubuntu' in low:
        return 'linux'
    return ''


def menu(cfg_text):
    """The menu's entries in their order: {title, id, classes, system, submenu} - submenu: the title of the submenu an
    entry is in ('' at the top level); a submenu itself is not an entry one starts."""
    entries, stack = [], []
    for line in (cfg_text or '').splitlines():
        m = ENTRY_RE.match(line)
        if m:
            kind, title, rest = m.group(1), m.group(2) if m.group(2) is not None else m.group(3), m.group(4)
            if line.rstrip().endswith('{'):
                stack.append((kind, title))
            if kind == 'menuentry':
                ident = ID_RE.search(rest)
                classes = CLASS_RE.findall(rest)
                inside = next((t for k, t in reversed(stack[:-1] if line.rstrip().endswith('{') else stack)
                               if k == 'submenu'), '')
                entries.append({'title': title, 'id': next((g for g in ident.groups() if g), '') if ident else '',
                                'classes': classes, 'system': system_of(title, classes), 'submenu': inside})
            continue
        if line.strip() == '}' and stack:
            stack.pop()
    return entries


def env(text):
    """The variables of grubenv (saved_entry, next_entry, ...)."""
    found = {}
    for line in (text or '').splitlines():
        if line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        found[key.strip()] = value.strip()
    return found


def grub_default(defaults_text):
    """GRUB_DEFAULT of /etc/default/grub ('0' when absent), its quotes taken off."""
    return setting(defaults_text, 'GRUB_DEFAULT', '0')


def entry_ref(entry):
    """What grub-reboot / grub-set-default take: the id, or the title path (Submenu>Title) without one."""
    if entry['id']:
        return entry['id']
    return (entry['submenu'] + '>' if entry['submenu'] else '') + entry['title']


def named(entries, ref):
    """The entry a GRUB variable names (an id, a title, Submenu>Title, or a top-level position), or None."""
    if ref is None or ref == '':
        return None
    for e in entries:
        if ref in (e['id'], e['title'], (e['submenu'] + '>' + e['title']) if e['submenu'] else None):
            return e
    if str(ref).isdigit():
        tops = [e for e in entries if not e['submenu']]
        i = int(ref)
        # a position counts the top-level entries and submenus; the parse sees every memtest of every platform, so
        # it is a guess past them - only the first few, before any conditional block, are reliable
        return tops[i] if i < len(tops) else None
    return None


def select(entries, selector):
    """The entries a word of --os names, as for the firmware: the id, the title, windows / linux, part of the title.
    Top-level entries before the submenus' (Ubuntu before its Advanced kernels)."""
    low = str(selector or '').strip().lower()
    if not low:
        return []
    ordered = [e for e in entries if not e['submenu']] + [e for e in entries if e['submenu']]
    rules = (lambda e: e['id'].lower() == low,
             lambda e: e['title'].lower() == low,
             lambda e: e['system'] == low and not e['submenu'],
             lambda e: low in e['title'].lower() and not e['submenu'],
             lambda e: low in e['title'].lower())
    for rule in rules:
        hits = [e for e in ordered if rule(e)]
        if hits:
            return hits
    return []


def shown(entries, every = False):
    """A list shows the systems at the top level (Ubuntu, Windows); --all every entry (kernels, memtest, firmware)."""
    return entries if every else [e for e in entries if e['system'] and not e['submenu']] or entries


def setting(defaults_text, key, default = ''):
    """A setting of /etc/default/grub (the last line that sets it), its quotes taken off."""
    value = default
    for line in (defaults_text or '').splitlines():
        m = re.match(r'^\s*' + re.escape(key) + r'=(.*)$', line)
        if m:
            value = m.group(1).strip().strip('"\'')
    return value


def set_keys(defaults_text, values):
    """/etc/default/grub with these settings: each line replaced (the first that sets it; later ones commented out), or
    added at the end; every other line as it was. (text, changed)"""
    out, done = [], set()
    for line in (defaults_text or '').splitlines():
        m = re.match(r'^\s*([A-Z_]+)=', line)
        key = m.group(1) if m else None
        if key in values:
            if key in done:
                out.append('# ' + line + '   # cmeta reboot-to: set above')
            else:
                out.append(f'{key}={values[key]}')
                done.add(key)
        else:
            out.append(line)
    out += [f'{k}={v}' for k, v in values.items() if k not in done]
    text = '\n'.join(out) + '\n'
    return text, text != (defaults_text if (defaults_text or '').endswith('\n') else (defaults_text or '') + '\n')
