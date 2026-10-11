# YoinkScript~ Language Manual

Welcome to **YoinkScript**, a functional, expression-oriented programming language featuring curried functions, mandatory manual memory management via a simulated heap, and a secure, allowlisted standard library. 

---

## 1. Syntax & Core Concepts

YoinkScript is an expression-oriented language. Every construct evaluates to a value. 

### Statement Sequencing (Let Chaining)
Unlike traditional imperative languages, YoinkScript **does not have a bare semicolon separator** to execute commands line-by-line. Instead, all execution sequences must be chained together inside the body of a `let` or `auto` binding. 

```ocaml
// ❌ INVALID syntax:
print "Hello";
print "World";

// 🍏 VALID syntax (Chained Execution):
let _unused1 = print "Hello";
let _unused2 = print "World";
"Final Return Value"
```

### Variables and Bindings
Variables are immutable by default and are declared using either `let` or `auto`. Both keywords are functionally interchangeable.
* Syntax: `let name = expression; body`
* Explicit type annotations (e.g., `: int`) are accepted by the parser but treated as comments/documentation by the evaluator.

```ocaml
let x: int = 10;
auto y = 20;
x + y
```

### Recursive Bindings
To define a recursive function, you must explicitly use the `rec` keyword.

```ocaml
let rec factorial = fn n ->
    if (n == 0) then { 1 } else { n * (factorial (n - 1)) };
factorial 5
```

---

## 2. Data Types

YoinkScript supports the following native data types:

| Data Type | Examples | Description |
| :--- | :--- | :--- |
| **Number** | `42`, `3.14` | Evaluates to Python `int` or `float` |
| **String** | `"Hello\n"` | Supports standard escape characters (`\n`, `\t`, `\r`, `\"`, `\\`) |
| **Boolean** | `true`, `false` | Standard logical flags |
| **Pointer** | `0x7fff0000 (Point*)` | Represents a raw memory address pointing to a Struct on the Heap |

---

## 3. Functions & Application (Currying)

All functions in YoinkScript are anonymous lambdas (`fn param -> body`) and take **exactly one argument**. Functions with multiple parameters are implemented via **Currying** (returning another function).

### Defining Functions
```ocaml
// A single-argument function
let square = fn x -> x * x;

// A curried function accepting multiple arguments
let multiply = fn x -> fn y -> x * y;
```

### Calling Functions (Application)
Arguments are passed sequentially, separated by spaces. You do not use parentheses or commas for function arguments.
```ocaml
// Calling a single-argument function
square 5

// Calling a curried function
multiply 4 3
```

---

## 4. Control Flow (Conditionals)

Conditionals are expressions and must evaluate to a value. Both the `then` and `else` branches are mandatory and must be present.

```ocaml
let max = fn x -> fn y ->
    if (x > y) then { x } else { y };
```

---

## 5. Manual Memory Management (Structs & Pointers)

YoinkScript brings C++ style raw pointers and heap allocations into a functional paradigm. All custom data structures are allocated on a managed memory heap.

### Defining a Struct
Struct fields can optionally include type descriptors separated by a colon (`:`).
```ocaml
struct Node {
    value: int;
    next: Pointer;
};
```

### Allocation (`new`)
The `new` keyword instantiates a struct onto the heap and returns a `PointerValue` representing its virtual 64-bit aligned memory address.
```ocaml
auto head = new Node{42, false};
```

### Pointer Dereferencing (`->` or `.`)
To access properties inside a struct instance on the heap, use the C++ style arrow operator (`->`) or dot operator (`.`).
```ocaml
auto val = head->value;
```

### Deallocation (`delete`)
To prevent memory leaks, manually release heap allocations using `delete`. Like `let`, a `delete` block must chain into a following execution body.
```ocaml
delete head;
"Memory is cleared!"
```

⚠️ **Warning:** YoinkScript will instantly throw a runtime error (`Segmentation Fault (Core Dumped)`) under the following conditions:
* **Double Free:** Trying to `delete` an address that was already freed.
* **Use-After-Free:** Trying to read or write via a pointer that has been deleted.
* **Null Pointer:** Trying to access an invalid memory address.

---

## 6. The Standard Library (Stdlib)

YoinkScript contains a highly secure standard library. Primitives are global functions that can be called natively.

### Cryptography & Encoding
* `sha256 data` - Returns the SHA-256 hex digest of a string.
* `sha1 data` - Returns the SHA-1 hex digest of a string.
* `md5 data` - Returns the MD5 checksum of a string.
* `hmac_sha256 key data` - Computes an HMAC-SHA256 signature.
* `base64_encode data` / `base64_decode encoded` - Converts text to/from Base64 encoding.
* `encrypt key plaintext` - Performs AES-128-CBC + HMAC symmetric encryption via a deterministic key derived from your passphrase.
* `decrypt key ciphertext` - Decrypts ciphertext. Throws an error if tampered with or if the key is incorrect.
* `random_token bytes` - Generates a secure random hex token (Accepts byte sizes up to `4096`).

### Sandboxed File I/O
All file operations are strictly sandboxed inside a system-designated environment directory. Absolute paths, directory traversal (`..`), or symlinks that try to break out of the sandbox will trigger a `PermissionError`.
* `file_exists path` - Returns `true` or `false`.
* `write_file path content` - Overwrites or creates a file.
* `append_file path content` - Appends text to a file.
* `read_file path` - Reads the full text contents of a sandboxed file.
* `delete_file path` - Deletes a sandboxed file.

### Allowlisted Process Execution
YoinkScript does not utilize a system shell, neutralizing shell injection vulnerabilities. It can only execute commands explicitly defined in its system registry allowlist:
* `list_allowed_apps ""` - Returns a comma-separated list of permitted apps (e.g., `echo`, `list_dir`, `whoami`, `hostname`, `date`, `python`).
* `run_app app_name arg_string` - Executes an allowed command with arguments safely passed as an argv array. Timeout is capped at 10 seconds.

### Networking (Outbound-only)
* `http_get url` - Fetches string responses from HTTP/HTTPS endpoints (Capped at a maximum response size of 5 MB).
* `http_post url body` - Sends a JSON POST request payload to a specified URL.
* `tcp_send host port message` - Opens a raw outbound TCP socket connection, transmits a payload, and captures the inbound response.

### Utilities
* `print value` - Outputs a value to the standard system console. Returns the value itself.
* `to_string value` - Formats integers, floats, or primitives into strings.
