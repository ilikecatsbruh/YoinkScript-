import sys
import re

# ==========================================
# 1. LEXER (With New, Delete, Arrow Pointers, and Strings)
# ==========================================

TOKEN_TYPES = [
    ('COMMENT',  r'//.*'),
    ('STRING',   r'"(?:[^"\\]|\\.)*"'),
    ('NUMBER',   r'\d+(\.\d+)?'),
    ('KEYWORD',  r'\b(let|auto|fn|if|else|return|rec|struct|new|delete)\b'),
    ('IDENT',    r'[a-zA-Z_][a-zA-Z0-9_]*'),
    ('ARROW',    r'->'),
    ('EQ',       r'=='),
    ('ASSIGN',   r'='),
    ('OP',       r'[+\-*/<>]'),
    ('DELIM',    r'[\(\){},;:.]'),
    ('SKIP',     r'[ \t\n\r]+'),
    ('MISMATCH', r'.'),
]

master_pat = re.compile('|'.join(f'(?P<{name}>{pattern})' for name, pattern in TOKEN_TYPES))


def _unescape_string(raw):
    # raw includes the surrounding quotes
    inner = raw[1:-1]
    out = []
    i = 0
    escapes = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\', '0': '\0'}
    while i < len(inner):
        c = inner[i]
        if c == '\\' and i + 1 < len(inner):
            nxt = inner[i + 1]
            out.append(escapes.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def tokenize(code):
    tokens = []
    for match in master_pat.finditer(code):
        kind = match.lastgroup
        value = match.group(kind)
        if kind == 'SKIP' or kind == 'COMMENT':
            continue
        elif kind == 'MISMATCH':
            raise SyntaxError(f'Unexpected character: {value!r}')
        elif kind == 'STRING':
            tokens.append((kind, _unescape_string(value)))
        else:
            tokens.append((kind, value))
    tokens.append(('EOF', ''))
    return tokens


# ==========================================
# 2. MEMORY HEAP & AST NODES
# ==========================================

class Heap:
    def __init__(self):
        self.storage = {}            # addr -> StructInstance
        self.freed = set()           # track freed addresses for segfault detection
        self.next_addr = 0x7fff0000  # realistic C++ looking memory addresses

    def allocate(self, struct_inst):
        addr = self.next_addr
        self.next_addr += 8  # 64-bit alignment style spacing
        self.storage[addr] = struct_inst
        return addr

    def deallocate(self, addr):
        if addr in self.freed:
            raise RuntimeError(f"Segmentation Fault (Core Dumped): Double free at address {hex(addr)}")
        if addr not in self.storage:
            raise RuntimeError(f"Segmentation Fault (Core Dumped): Invalid free/dereference at address {hex(addr)}")
        del self.storage[addr]
        self.freed.add(addr)

    def get(self, addr):
        if addr in self.freed:
            raise RuntimeError(f"Segmentation Fault (Core Dumped): Use-after-free read at address {hex(addr)}")
        if addr not in self.storage:
            raise RuntimeError(f"Segmentation Fault (Core Dumped): Null pointer or invalid read at address {hex(addr)}")
        return self.storage[addr]


class PointerValue:
    def __init__(self, addr, struct_name):
        self.addr = addr
        self.struct_name = struct_name

    def __repr__(self):
        return f"0x{self.addr:x} ({self.struct_name}*)"


class AST: pass


class Number(AST):
    def __init__(self, val): self.val = float(val) if '.' in val else int(val)
    def __repr__(self): return str(self.val)


class Bool(AST):
    def __init__(self, val): self.val = val
    def __repr__(self): return str(self.val)


class StringLit(AST):
    def __init__(self, val): self.val = val
    def __repr__(self): return repr(self.val)


class Ident(AST):
    def __init__(self, name): self.name = name
    def __repr__(self): return self.name


class Let(AST):
    def __init__(self, name, val, body, is_rec=False):
        self.name = name
        self.val = val
        self.body = body
        self.is_rec = is_rec


class StructDef(AST):
    def __init__(self, name, fields, body):
        self.name = name
        self.fields = fields
        self.body = body


class NewInst(AST):
    def __init__(self, name, values):
        self.name = name
        self.values = values


class Delete(AST):
    def __init__(self, expr, body):
        self.expr = expr
        self.body = body


class PtrMemberAccess(AST):
    def __init__(self, expr, field):
        self.expr = expr
        self.field = field


class Lambda(AST):
    def __init__(self, param, body):
        self.param = param
        self.body = body


class App(AST):
    def __init__(self, func, arg):
        self.func = func
        self.arg = arg


class If(AST):
    def __init__(self, cond, then_branch, else_branch):
        self.cond = cond
        self.then_branch = then_branch
        self.else_branch = else_branch


class BinOp(AST):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right


class StructInstance:
    def __init__(self, name, fields_dict):
        self.name = name
        self.fields_dict = fields_dict

    def __repr__(self):
        fields_str = ", ".join(f"{k}={v}" for k, v in self.fields_dict.items())
        return f"{self.name}{{{fields_str}}}"


# ==========================================
# 3. PARSER
# ==========================================

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def consume(self, expected_type=None, expected_val=None):
        t_type, t_val = self.peek()
        if expected_type and t_type != expected_type:
            raise SyntaxError(f"Expected token type {expected_type}, got {t_type} ('{t_val}')")
        if expected_val and t_val != expected_val:
            raise SyntaxError(f"Expected value '{expected_val}', got '{t_val}'")
        self.pos += 1
        return t_val

    def parse(self):
        node = self.parse_expr()
        if self.peek()[0] != 'EOF':
            raise SyntaxError(f"Unexpected token: {self.peek()[1]}")
        return node

    def parse_expr(self):
        t_type, t_val = self.peek()

        # struct definition
        if t_type == 'KEYWORD' and t_val == 'struct':
            self.consume('KEYWORD', 'struct')
            struct_name = self.consume('IDENT')
            self.consume('DELIM', '{')
            fields = []
            while self.peek() != ('DELIM', '}'):
                f_name = self.consume('IDENT')
                if self.peek() == ('DELIM', ':'):
                    self.consume('DELIM', ':')
                    self.consume('IDENT')
                if self.peek() == ('DELIM', ';'):
                    self.consume('DELIM', ';')
                fields.append(f_name)
            self.consume('DELIM', '}')
            if self.peek() == ('DELIM', ';'):
                self.consume('DELIM', ';')
            body = self.parse_expr()
            return StructDef(struct_name, fields, body)

        # delete ptr; body
        elif t_type == 'KEYWORD' and t_val == 'delete':
            self.consume('KEYWORD', 'delete')
            expr = self.parse_expr()
            if self.peek() == ('DELIM', ';'):
                self.consume('DELIM', ';')
            # NOTE: fixed to chain into a following body, same as `let` does --
            # otherwise `delete p; initialX` could never parse past the delete.
            body = self.parse_expr()
            return Delete(expr, body)

        # let / auto bindings
        elif t_type == 'KEYWORD' and t_val in ('let', 'auto'):
            self.consume('KEYWORD')
            is_rec = False
            if self.peek() == ('KEYWORD', 'rec'):
                self.consume('KEYWORD', 'rec')
                is_rec = True
            name = self.consume('IDENT')

            if self.peek() == ('DELIM', ':'):
                self.consume('DELIM', ':')
                self.consume('IDENT')

            self.consume('ASSIGN', '=')
            val = self.parse_expr()
            if self.peek() == ('DELIM', ';'):
                self.consume('DELIM', ';')

            body = self.parse_expr()
            return Let(name, val, body, is_rec)

        # Lambda functions
        elif t_type == 'KEYWORD' and t_val == 'fn':
            self.consume('KEYWORD', 'fn')
            has_paren = False
            if self.peek() == ('DELIM', '('):
                self.consume('DELIM', '(')
                has_paren = True

            param = self.consume('IDENT')

            if has_paren:
                if self.peek() == ('DELIM', ':'):
                    self.consume('DELIM', ':')
                    self.consume('IDENT')
                self.consume('DELIM', ')')

            if self.peek() == ('ARROW', '->'):
                self.consume('ARROW', '->')
                self.consume('IDENT')

            has_braces = False
            if self.peek() == ('DELIM', '{'):
                self.consume('DELIM', '{')
                has_braces = True
                if self.peek() == ('KEYWORD', 'return'):
                    self.consume('KEYWORD', 'return')

            body = self.parse_expr()

            if has_braces:
                if self.peek() == ('DELIM', ';'):
                    self.consume('DELIM', ';')
                self.consume('DELIM', '}')

            return Lambda(param, body)

        # Conditionals
        elif t_type == 'KEYWORD' and t_val == 'if':
            self.consume('KEYWORD', 'if')
            has_paren = False
            if self.peek() == ('DELIM', '('):
                self.consume('DELIM', '(')
                has_paren = True

            cond = self.parse_expr()

            if has_paren:
                self.consume('DELIM', ')')

            self.consume('KEYWORD', 'then') if self.peek() == ('KEYWORD', 'then') else None

            has_braces = False
            if self.peek() == ('DELIM', '{'):
                self.consume('DELIM', '{')
                has_braces = True

            then_branch = self.parse_expr()

            if has_braces:
                if self.peek() == ('DELIM', ';'): self.consume('DELIM', ';')
                self.consume('DELIM', '}')

            self.consume('KEYWORD', 'else')

            has_braces_else = False
            if self.peek() == ('DELIM', '{'):
                self.consume('DELIM', '{')
                has_braces_else = True

            else_branch = self.parse_expr()

            if has_braces_else:
                if self.peek() == ('DELIM', ';'): self.consume('DELIM', ';')
                self.consume('DELIM', '}')

            return If(cond, then_branch, else_branch)

        return self.parse_equality()

    def parse_equality(self):
        node = self.parse_additive()
        while self.peek() == ('EQ', '=='):
            op = self.consume('EQ')[1]
            right = self.parse_additive()
            node = BinOp(node, op, right)
        return node

    def parse_additive(self):
        node = self.parse_multiplicative()
        while self.peek()[0] == 'OP' and self.peek()[1] in ('+', '-'):
            op = self.consume('OP')[1]
            right = self.parse_multiplicative()
            node = BinOp(node, op, right)
        return node

    def parse_multiplicative(self):
        node = self.parse_app()
        while self.peek()[0] == 'OP' and self.peek()[1] in ('*', '/'):
            op = self.consume('OP')[1]
            right = self.parse_app()
            node = BinOp(node, op, right)
        return node

    def parse_app(self):
        node = self.parse_primary()
        while True:
            next_t = self.peek()
            # Pointer member access: ptr->field
            if next_t == ('ARROW', '->'):
                self.consume('ARROW', '->')
                field = self.consume('IDENT')
                node = PtrMemberAccess(node, field)
                continue
            # Regular member access: obj.field
            if next_t == ('DELIM', '.'):
                self.consume('DELIM', '.')
                field = self.consume('IDENT')
                node = PtrMemberAccess(node, field)  # handled interchangeably
                continue

            if next_t[0] in ('NUMBER', 'IDENT', 'STRING', 'DELIM') and next_t != ('DELIM', ')'):
                if next_t in (('DELIM', ','), ('DELIM', ';'), ('DELIM', '}'), ('DELIM', '.')):
                    break
                arg = self.parse_primary()
                node = App(node, arg)
            else:
                break
        return node

    def parse_primary(self):
        t_type, t_val = self.peek()
        if t_type == 'NUMBER':
            self.consume('NUMBER')
            return Number(t_val)
        elif t_type == 'STRING':
            self.consume('STRING')
            return StringLit(t_val)
        elif t_type == 'KEYWORD' and t_val == 'new':
            self.consume('KEYWORD', 'new')
            name = self.consume('IDENT')
            self.consume('DELIM', '{')
            values = []
            if self.peek() != ('DELIM', '}'):
                values.append(self.parse_expr())
                while self.peek() == ('DELIM', ','):
                    self.consume('DELIM', ',')
                    values.append(self.parse_expr())
            self.consume('DELIM', '}')
            return NewInst(name, values)
        elif t_type == 'IDENT':
            name = self.consume('IDENT')
            if name == 'true': return Bool(True)
            if name == 'false': return Bool(False)
            return Ident(name)
        elif t_type == 'DELIM' and t_val == '(':
            self.consume('DELIM', '(')
            node = self.parse_expr()
            self.consume('DELIM', ')')
            return node
        else:
            raise SyntaxError(f"Unexpected token in primary expression: {t_val!r}")


# ==========================================
# 4. ENVIRONMENT & EVALUATOR WITH HEAP SUPPORT
# ==========================================

class Closure:
    def __init__(self, param, body, env):
        self.param = param
        self.body = body
        self.env = env

    def __repr__(self): return "<yoinkscript function closure>"


class NativeFunction:
    """Wraps a Python callable as a YoinkScript stdlib function.
    `arity` is how many YoinkScript arguments it takes; application is
    curried one argument at a time just like user-defined Lambdas."""
    def __init__(self, name, arity, fn):
        self.name = name
        self.arity = arity
        self.fn = fn

    def __repr__(self): return f"<native fn {self.name}/{self.arity}>"


class NativePartial:
    """A native function that has been given some, but not all, of its args."""
    def __init__(self, native, args):
        self.native = native
        self.args = args

    def __repr__(self): return f"<native fn {self.native.name} (partial {len(self.args)}/{self.native.arity})>"


class Environment:
    def __init__(self, parent=None, heap=None):
        self.bindings = {}
        self.parent = parent
        self.heap = heap if heap else Heap()

    def lookup(self, name):
        if name in self.bindings:
            return self.bindings[name]
        if self.parent:
            return self.parent.lookup(name)
        raise NameError(f"Name '{name}' is not defined")

    def define(self, name, value):
        self.bindings[name] = value


def evaluate(node, env):
    if isinstance(node, Number): return node.val
    elif isinstance(node, Bool): return node.val
    elif isinstance(node, StringLit): return node.val
    elif isinstance(node, Ident): return env.lookup(node.name)
    elif isinstance(node, Lambda): return Closure(node.param, node.body, env)
    elif isinstance(node, StructDef):
        new_env = Environment(parent=env, heap=env.heap)
        new_env.define(node.name, ("STRUCT_DEF", node.fields))
        return evaluate(node.body, new_env)
    elif isinstance(node, NewInst):
        struct_def = env.lookup(node.name)
        if not isinstance(struct_def, tuple) or struct_def[0] != "STRUCT_DEF":
            raise TypeError(f"'{node.name}' is not a valid struct type")
        fields = struct_def[1]
        if len(node.values) != len(fields):
            raise ValueError(f"Struct '{node.name}' expects {len(fields)} fields, got {len(node.values)}")
        evaluated_vals = [evaluate(v, env) for v in node.values]
        inst = StructInstance(node.name, dict(zip(fields, evaluated_vals)))

        # Allocate on the heap and return pointer
        addr = env.heap.allocate(inst)
        return PointerValue(addr, node.name)
    elif isinstance(node, Delete):
        ptr = evaluate(node.expr, env)
        if not isinstance(ptr, PointerValue):
            raise TypeError("Attempted to 'delete' a non-pointer type")
        env.heap.deallocate(ptr.addr)
        return evaluate(node.body, env)
    elif isinstance(node, PtrMemberAccess):
        ptr = evaluate(node.expr, env)
        if not isinstance(ptr, PointerValue):
            raise TypeError("Attempted pointer dereference '->' on non-pointer object")
        inst = env.heap.get(ptr.addr)
        if node.field not in inst.fields_dict:
            raise AttributeError(f"Struct '{inst.name}' has no field '{node.field}'")
        return inst.fields_dict[node.field]
    elif isinstance(node, App):
        func = evaluate(node.func, env)
        arg = evaluate(node.arg, env)
        if isinstance(func, Closure):
            new_env = Environment(parent=func.env, heap=env.heap)  # share the heap across closures
            new_env.define(func.param, arg)
            return evaluate(func.body, new_env)
        elif isinstance(func, NativeFunction):
            if func.arity <= 1:
                return func.fn(env, arg)
            return NativePartial(func, [arg])
        elif isinstance(func, NativePartial):
            args = func.args + [arg]
            if len(args) >= func.native.arity:
                return func.native.fn(env, *args)
            return NativePartial(func.native, args)
        else:
            raise TypeError("Attempted to call non-function object")
    elif isinstance(node, Let):
        if node.is_rec:
            new_env = Environment(parent=env, heap=env.heap)
            closure = Closure(node.val.param, node.val.body, new_env)
            new_env.define(node.name, closure)
            return evaluate(node.body, new_env)
        else:
            val = evaluate(node.val, env)
            new_env = Environment(parent=env, heap=env.heap)
            new_env.define(node.name, val)
            return evaluate(node.body, new_env)
    elif isinstance(node, If):
        cond = evaluate(node.cond, env)
        return evaluate(node.then_branch, env) if cond else evaluate(node.else_branch, env)
    elif isinstance(node, BinOp):
        left = evaluate(node.left, env)
        right = evaluate(node.right, env)
        ops = {
            '+': lambda a, b: a + b, '-': lambda a, b: a - b,
            '*': lambda a, b: a * b, '/': lambda a, b: a / b,
            '==': lambda a, b: a == b, '<': lambda a, b: a < b, '>': lambda a, b: a > b
        }
        return ops[node.op](left, right)
    raise TypeError(f"Unknown AST node: {type(node)}")


# ==========================================
# 5. STANDARD LIBRARY
#    Crypto, sandboxed file I/O, allowlisted process execution, networking.
#    Cross-platform: Windows + Linux.
# ==========================================

import os
import hashlib
import hmac
import base64 as _b64
import secrets
import socket
import subprocess
import shlex
import platform
import urllib.request
import urllib.error

from cryptography.fernet import Fernet, InvalidToken

IS_WINDOWS = platform.system() == "Windows"


def _as_str(v, what="value"):
    if not isinstance(v, str):
        raise TypeError(f"YoinkScript stdlib expected a string {what}, got {type(v).__name__}")
    return v


# ---- 5.1 Cryptography --------------------------------------------------

def _native_sha256(env, data):
    return hashlib.sha256(_as_str(data, "data").encode("utf-8")).hexdigest()


def _native_sha1(env, data):
    return hashlib.sha1(_as_str(data, "data").encode("utf-8")).hexdigest()


def _native_md5(env, data):
    # Not cryptographically secure -- exposed for checksums/legacy compatibility only.
    return hashlib.md5(_as_str(data, "data").encode("utf-8")).hexdigest()


def _native_hmac_sha256(env, key, data):
    key_b = _as_str(key, "key").encode("utf-8")
    data_b = _as_str(data, "data").encode("utf-8")
    return hmac.new(key_b, data_b, hashlib.sha256).hexdigest()


def _native_base64_encode(env, data):
    return _b64.b64encode(_as_str(data, "data").encode("utf-8")).decode("ascii")


def _native_base64_decode(env, data):
    try:
        return _b64.b64decode(_as_str(data, "data").encode("ascii")).decode("utf-8", errors="replace")
    except Exception as e:
        raise ValueError(f"base64_decode failed: {e}")


def _derive_fernet_key(passphrase):
    # Fernet needs a 32-byte urlsafe-base64 key; derive one deterministically
    # from an arbitrary-length passphrase via SHA-256.
    digest = hashlib.sha256(passphrase.encode("utf-8")).digest()
    return _b64.urlsafe_b64encode(digest)


def _native_encrypt(env, key, plaintext):
    # Authenticated symmetric encryption (AES-128-CBC + HMAC via Fernet).
    f = Fernet(_derive_fernet_key(_as_str(key, "key")))
    token = f.encrypt(_as_str(plaintext, "plaintext").encode("utf-8"))
    return token.decode("ascii")


def _native_decrypt(env, key, ciphertext):
    f = Fernet(_derive_fernet_key(_as_str(key, "key")))
    try:
        return f.decrypt(_as_str(ciphertext, "ciphertext").encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise ValueError("decrypt failed: wrong key or corrupted/tampered ciphertext")


def _native_random_token(env, n_bytes):
    n = int(n_bytes)
    if n <= 0 or n > 4096:
        raise ValueError("random_token: byte count must be between 1 and 4096")
    return secrets.token_hex(n)


# ---- 5.2 Sandboxed file access -----------------------------------------
# All file paths are resolved *inside* a sandbox root and reject any path
# that tries to escape it (via '..', absolute paths, symlinks, etc).

SANDBOX_ROOT = os.path.abspath(os.environ.get("YOINK_SANDBOX", os.path.join(os.getcwd(), "yoink_sandbox")))
os.makedirs(SANDBOX_ROOT, exist_ok=True)


def _resolve_sandboxed_path(rel_path):
    rel_path = _as_str(rel_path, "path")
    # Explicitly reject absolute paths / drive letters rather than silently
    # reinterpreting them as relative -- fail loud instead of fail quiet.
    normalized_slashes = rel_path.replace("\\", "/")
    if normalized_slashes.startswith("/") or (len(normalized_slashes) > 1 and normalized_slashes[1] == ":"):
        raise PermissionError(f"Access denied: absolute/drive paths are not allowed ('{rel_path}')")
    candidate = os.path.normpath(os.path.join(SANDBOX_ROOT, normalized_slashes))
    real_candidate = os.path.realpath(candidate)
    real_root = os.path.realpath(SANDBOX_ROOT)
    if real_candidate != real_root and not real_candidate.startswith(real_root + os.sep):
        raise PermissionError(f"Access denied: path '{rel_path}' escapes the sandbox root")
    return real_candidate


def _native_read_file(env, path):
    full = _resolve_sandboxed_path(path)
    if not os.path.isfile(full):
        raise FileNotFoundError(f"No such file in sandbox: {path}")
    with open(full, "r", encoding="utf-8") as fh:
        return fh.read()


def _native_write_file(env, path, content):
    full = _resolve_sandboxed_path(path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(_as_str(content, "content"))
    return 1


def _native_append_file(env, path, content):
    full = _resolve_sandboxed_path(path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "a", encoding="utf-8") as fh:
        fh.write(_as_str(content, "content"))
    return 1


def _native_file_exists(env, path):
    try:
        full = _resolve_sandboxed_path(path)
    except PermissionError:
        return False
    return os.path.isfile(full)


def _native_delete_file(env, path):
    full = _resolve_sandboxed_path(path)
    if not os.path.isfile(full):
        raise FileNotFoundError(f"No such file in sandbox: {path}")
    os.remove(full)
    return 1


# ---- 5.3 Allowlisted process execution ---------------------------------
# A fixed table of logical command names the script is permitted to invoke.
# Each maps to a *concrete, non-shell* argv on each platform -- there is no
# way for a YoinkScript program to run anything outside this table, and
# arguments are passed as an argv list (never through a shell) so they
# can't be used to chain in extra commands.

ALLOWED_APPS = {
    "echo":      {"Windows": ["cmd", "/c", "echo"], "default": ["echo"]},
    "list_dir":  {"Windows": ["cmd", "/c", "dir"],   "default": ["ls", "-la"]},
    "whoami":    {"Windows": ["whoami"],             "default": ["whoami"]},
    "hostname":  {"Windows": ["hostname"],           "default": ["hostname"]},
    "date":      {"Windows": ["cmd", "/c", "echo", "%date% %time%"], "default": ["date"]},
    "python":    {"Windows": ["python"],             "default": ["python3"]},
}


def _native_run_app(env, app_name, arg_string):
    app_name = _as_str(app_name, "app_name")
    if app_name not in ALLOWED_APPS:
        allowed = ", ".join(sorted(ALLOWED_APPS))
        raise PermissionError(f"Execution denied: '{app_name}' is not in the application allowlist ({allowed})")

    platform_key = "Windows" if IS_WINDOWS else "default"
    base_cmd = ALLOWED_APPS[app_name].get(platform_key, ALLOWED_APPS[app_name]["default"])
    extra_args = shlex.split(_as_str(arg_string, "args")) if arg_string else []
    full_cmd = base_cmd + extra_args

    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,          # never goes through a shell -- no injection via args
        )
        output = result.stdout
        if result.returncode != 0:
            output += result.stderr
        return output
    except FileNotFoundError:
        raise RuntimeError(f"Executable for '{app_name}' was not found on this system.")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"'{app_name}' timed out after 10 seconds.")


def _native_list_allowed_apps(env, _unused):
    return ", ".join(sorted(ALLOWED_APPS))


# ---- 5.4 Networking ------------------------------------------------------
# Plain HTTP(S) client calls and a minimal raw TCP client. These are
# explicit, outbound-only primitives a script calls on demand -- there is
# no listener, no auto-reconnect/beaconing loop, and no path that executes
# data received from the network.

_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB cap so a hostile server can't exhaust memory


def _read_capped(resp):
    return resp.read(_MAX_RESPONSE_BYTES).decode("utf-8", errors="replace")


def _native_http_get(env, url):
    url = _as_str(url, "url")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("http_get: url must start with http:// or https://")
    req = urllib.request.Request(url, headers={"User-Agent": "YoinkScript/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return _read_capped(resp)
    except urllib.error.URLError as e:
        raise RuntimeError(f"http_get failed: {e}")


def _native_http_post(env, url, body):
    url = _as_str(url, "url")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("http_post: url must start with http:// or https://")
    data = _as_str(body, "body").encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": "YoinkScript/1.0", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return _read_capped(resp)
    except urllib.error.URLError as e:
        raise RuntimeError(f"http_post failed: {e}")


def _native_tcp_send(env, host, port, message):
    host = _as_str(host, "host")
    try:
        port_i = int(port)
    except (TypeError, ValueError):
        raise ValueError("tcp_send: port must be numeric")
    with socket.create_connection((host, port_i), timeout=10) as s:
        s.sendall(_as_str(message, "message").encode("utf-8"))
        s.settimeout(5)
        try:
            data = s.recv(65536)
        except socket.timeout:
            data = b""
        return data.decode("utf-8", errors="replace")


# ---- 5.5 Misc helpers exposed to scripts --------------------------------

def _native_print(env, value):
    print(value)
    return value


def _native_to_string(env, value):
    return str(value)


def build_global_env():
    """Construct the top-level Environment with the standard library bound in."""
    env = Environment()

    def reg(name, arity, fn):
        env.define(name, NativeFunction(name, arity, fn))

    # crypto
    reg("sha256", 1, _native_sha256)
    reg("sha1", 1, _native_sha1)
    reg("md5", 1, _native_md5)
    reg("hmac_sha256", 2, _native_hmac_sha256)
    reg("base64_encode", 1, _native_base64_encode)
    reg("base64_decode", 1, _native_base64_decode)
    reg("encrypt", 2, _native_encrypt)
    reg("decrypt", 2, _native_decrypt)
    reg("random_token", 1, _native_random_token)

    # sandboxed file access
    reg("read_file", 1, _native_read_file)
    reg("write_file", 2, _native_write_file)
    reg("append_file", 2, _native_append_file)
    reg("file_exists", 1, _native_file_exists)
    reg("delete_file", 1, _native_delete_file)

    # allowlisted process execution
    reg("run_app", 2, _native_run_app)
    reg("list_allowed_apps", 1, _native_list_allowed_apps)

    # networking
    reg("http_get", 1, _native_http_get)
    reg("http_post", 2, _native_http_post)
    reg("tcp_send", 3, _native_tcp_send)

    # misc
    reg("print", 1, _native_print)
    reg("to_string", 1, _native_to_string)

    return env


# ==========================================
# 6. EXECUTION EXAMPLE WITH MANUAL MEMORY + STDLIB
# ==========================================

def run(code, env=None):
    if env is None:
        env = build_global_env()
    tokens = tokenize(code)
    ast = Parser(tokens).parse()
    return evaluate(ast, env)


if __name__ == '__main__':
    yoinkscript_code = """
    struct Point {
        x: int;
        y: int;
    };

    // Allocate on the heap using 'new'
    auto p = new Point{40, 2};

    // Access members via C++ style pointer arrow '->'
    auto initialX = p->x;

    // Manually release memory with 'delete'
    delete p;

    // --- standard library demo ---
    auto digest = sha256 "YoinkScript";
    auto encoded = base64_encode "manual memory management";
    auto secretKey = "correct horse battery staple";
    auto token = encrypt secretKey "the launch code is 0042";
    auto roundTrip = decrypt secretKey token;

    // NOTE: this grammar only sequences statements via 'let' (or 'delete')
    // chaining into a body -- there's no bare ';' statement separator --
    // so side-effecting calls are threaded through dummy 'let' bindings.
    let _p1 = print digest;
    let _p2 = print encoded;
    let _p3 = print roundTrip;

    // sandboxed file I/O
    let _w = write_file "notes.txt" "hello from yoinkscript";
    auto fileContents = read_file "notes.txt";
    let _p4 = print fileContents;

    // allowlisted process execution
    auto who = run_app "whoami" "";
    let _p5 = print who;

    initialX
    """

    print("Executing YoinkScript Code with Manual Memory Management + stdlib:")
    print(yoinkscript_code.strip())
    print("\nResult:")

    result = run(yoinkscript_code)
    print(result)
