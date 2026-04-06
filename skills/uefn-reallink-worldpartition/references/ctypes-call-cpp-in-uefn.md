# 参考：在 UEFN 沙箱中通过 Python ctypes 调用任意 C++ 函数

## 背景

UEFN 编辑器沙箱内的 Python 环境只能调用 `UFUNCTION` 标记的函数。大量 C++ API（虚函数、非虚成员函数、全局函数）无法直接使用。但 `ctypes` 模块可以正常工作，我们利用它建立了一条完整的**从 Python 调用任意 C++ 函数**的路径。

本文档记录了该路径的完整技术方案，已在 `GetResourceSizeEx` 内存审计中验证通过（549,400 个 UObject，9.7 秒完成）。

---

## 1. UEFN 进程结构

### 模块布局

UEFN 编辑器是 **monolithic shipping build**，整个引擎编译到两个巨型 DLL 中：

| 模块 | 大小 | 内容 |
|------|------|------|
| `UnrealEditorFortnite-Engine-Win64-Shipping.dll` | ~774 MB | Core, CoreUObject, Engine 及所有引擎模块 |
| `UnrealEditorFortnite-Common-Win64-Shipping.dll` | ~374 MB | 公共库（只有少量 operator new/delete 导出） |
| `UnrealEditorFortnite-Win64-Shipping.exe` | ~400 KB | 主入口 |

### 导出符号

Engine DLL 导出了 **32,000+ 个 MSVC mangled C++ 符号**。所有标记了 `CORE_API`、`COREUOBJECT_API`、`ENGINE_API` 等 dllexport 宏的函数都可通过 `GetProcAddress` 获取。

### 可用的 Win32 API

| API | 是否可用 | 说明 |
|-----|---------|------|
| `GetModuleHandleW` | ✓ | 需要设置 `restype = c_uint64`（见下文注意事项） |
| `GetProcAddress` | ✓ | 同上 |
| `CreateToolhelp32Snapshot` + `Module32FirstW/NextW` | ✓ | 可枚举所有 290+ 已加载模块 |
| `VirtualQuery` | ⚠ | 参数为 64 位地址时需小心 overflow |
| `EnumProcessModulesEx` | ✗ | 返回 ERROR_INVALID_HANDLE |

---

## 2. 基础设施：ctypes 读写内存

### 读取任意内存地址

```python
import ctypes

def read_u64(addr: int) -> int:
    """读取指定地址处的 8 字节无符号整数。"""
    return ctypes.c_uint64.from_address(addr).value

def read_bytes(addr: int, size: int) -> bytes:
    """读取指定地址处的原始字节。"""
    buf = (ctypes.c_uint8 * size)()
    ctypes.memmove(buf, addr, size)
    return bytes(buf)
```

### 从 Python wrapper 获取 UObject 原生指针

```python
def get_uobject_ptr(obj) -> int:
    """从 unreal.Object Python wrapper 提取 UObject* 原生指针。
    
    Python wrapper 对象内部布局：
      id(obj) + 0x00: PyObject header
      id(obj) + 0x10: UObject* native_ptr  ← 我们需要这个
    """
    return ctypes.c_uint64.from_address(id(obj) + 16).value
```

### UObject 内存布局

```
UObject* 指向的内存：
  +0x00: void** vtable_ptr      ← 虚函数表指针
  +0x08: (alignment padding)
  +0x10: UClass* ClassPrivate   ← 类信息
  +0x18: (其他字段...)
  +0x28: UObject* OuterPrivate  ← 外部对象
```

读取 vtable：

```python
obj_ptr = get_uobject_ptr(some_unreal_object)
vtable = read_u64(obj_ptr)           # vtable 指针
func_addr = read_u64(vtable + slot * 8)  # 第 N 个虚函数的地址
```

---

## 3. 解析 DLL 导出符号

### 关键：正确设置 ctypes 类型

**必须**将 `GetModuleHandleW` 和 `GetProcAddress` 的返回类型设为 `c_uint64`，否则 64 位地址会被截断为 32 位导致错误结果。

```python
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ❌ 错误 — 默认 restype 是 c_int，64 位地址会被截断为负数
# handle = k32.GetModuleHandleW("some.dll")

# ✓ 正确
k32.GetModuleHandleW.restype = ctypes.c_uint64
k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]

k32.GetProcAddress.restype = ctypes.c_uint64
k32.GetProcAddress.argtypes = [ctypes.c_uint64, ctypes.c_char_p]
```

### 获取 DLL 句柄

```python
engine_h = k32.GetModuleHandleW("UnrealEditorFortnite-Engine-Win64-Shipping.dll")
# 返回值如 0x7ff996710000
```

### 获取函数地址

函数名使用 **MSVC C++ mangled name**（字节串）：

```python
addr = k32.GetProcAddress(engine_h, b"?GetTotalMemoryBytes@FResourceSizeEx@@QEBA_KXZ")
# 返回值如 0x7ff9984b7550
```

### MSVC Name Mangling 规则速查

| 前缀 | 含义 |
|------|------|
| `??0Foo@@` | `Foo` 的构造函数 |
| `??1Foo@@` | `Foo` 的析构函数 |
| `?Method@Class@@` | `Class::Method` |
| `QEAA` | `public: __cdecl` (非 const, 返回引用 this 所在类) |
| `QEBA` | `public: __cdecl const` |
| `UEAA` | `public: virtual __cdecl` |
| `_KXZ` | 返回 `unsigned __int64` (`SIZE_T`), 无参数 |
| `W4Type@EResourceSizeMode@@` | 参数类型 `EResourceSizeMode::Type` (enum) |
| `AEAUFoo@@` | 引用参数 `Foo&` |

获取 mangled name 的方法：
- 在开源引擎中用 `dumpbin /EXPORTS module.dll` 或 Visual Studio 的 Decorated Name 功能
- 或者按 MSVC 规则手动拼接

### 枚举模块（不知道 DLL 名称时）

```python
class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("GlblcntUsage", ctypes.wintypes.DWORD),
        ("ProccntUsage", ctypes.wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", ctypes.wintypes.DWORD),
        ("hModule", ctypes.c_void_p),
        ("szModule", ctypes.c_wchar * 256),
        ("szExePath", ctypes.c_wchar * 260),
    ]

pid = k32.GetCurrentProcessId()
snap = k32.CreateToolhelp32Snapshot(0x00000008 | 0x00000010, pid)
me = MODULEENTRY32W()
me.dwSize = ctypes.sizeof(MODULEENTRY32W)
if k32.Module32FirstW(snap, ctypes.byref(me)):
    while True:
        print(me.szModule, hex(me.modBaseAddr), me.modBaseSize)
        if not k32.Module32NextW(snap, ctypes.byref(me)):
            break
k32.CloseHandle(snap)
```

### 在 PE 导出表中搜索符号

当需要查找包含特定关键字的所有导出时：

```python
def read_u32(addr):
    return ctypes.c_uint32.from_address(addr).value

base = engine_h  # DLL 基地址
pe_off = read_u32(base + 0x3C)
export_rva = read_u32(base + pe_off + 24 + 112)
export_dir = base + export_rva
num_names = read_u32(export_dir + 24)
names_rva = read_u32(export_dir + 32)
name_ptrs = base + names_rva

for i in range(num_names):
    name_rva = read_u32(name_ptrs + i * 4)
    name = ctypes.string_at(base + name_rva, 200).decode("ascii", errors="replace")
    if "FResourceSizeEx" in name:
        print(name)
```

> ⚠ 注意：遍历 32K+ 导出名称较慢，且部分 `string_at` 读取可能跨页触发访问违规。建议先用 `GetProcAddress` 精确查找。

---

## 4. 调用 C++ 函数

### MSVC x64 调用约定

Windows x64 统一使用 **Microsoft x64 calling convention**：
- 前 4 个整数/指针参数：`RCX, RDX, R8, R9`
- 浮点用 `XMM0-XMM3`
- 返回值在 `RAX`（整数）或 `XMM0`（浮点）
- 调用者清理栈（caller clean-up）

对于 C++ 成员函数：
- `this` 指针作为第一个参数（`RCX`）
- 其余参数顺延

### 构建 CFUNCTYPE 包装器

```python
# void UObject::GetResourceSizeEx(FResourceSizeEx&)
# 等价于 C：void func(UObject* this, FResourceSizeEx* res)
# RCX = this, RDX = &res
VoidFunc_2Ptr = ctypes.CFUNCTYPE(None, ctypes.c_uint64, ctypes.c_uint64)

# SIZE_T FResourceSizeEx::GetTotalMemoryBytes() const
# 等价于 C：uint64 func(FResourceSizeEx* this)
# RCX = this, 返回 RAX
U64Func_1Ptr = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint64)

# FResourceSizeEx::FResourceSizeEx(EResourceSizeMode::Type)
# 等价于 C：FResourceSizeEx* func(FResourceSizeEx* this, int mode)
# RCX = this, EDX = mode, 返回 RAX (this)
CtorFunc = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint64, ctypes.c_int32)
```

### 调用非虚成员函数

直接用 `GetProcAddress` 获取的地址调用：

```python
get_total_addr = k32.GetProcAddress(engine_h, b"?GetTotalMemoryBytes@...")
GetTotal = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint64)(get_total_addr)

result = GetTotal(buffer_address)  # this = buffer_address
```

### 调用虚函数（virtual dispatch）

通过 vtable 间接调用，实现多态：

```python
SLOT = 69  # GetResourceSizeEx 在 UEFN 中的 vtable slot

obj_ptr = get_uobject_ptr(some_object)
vtable = read_u64(obj_ptr)                      # 读取 vtable 指针
func_addr = read_u64(vtable + SLOT * 8)          # 读取第 N 个 slot
VCall = ctypes.CFUNCTYPE(None, ctypes.c_uint64, ctypes.c_uint64)
VCall(func_addr)(obj_ptr, buffer_address)         # 虚调用
```

---

## 5. 确定虚函数的 vtable slot

### 方法 A：在开源引擎中编译辅助代码（可能不准确）

在开源 UE 源码中，通过成员函数指针 + vtable 搜索来确定 slot：

```cpp
using FuncType = void (UObject::*)(FResourceSizeEx&);
FuncType FuncPtr = &UObject::GetResourceSizeEx;
void* FuncAddr = *reinterpret_cast<void**>(&FuncPtr);
// 搜索 vtable 匹配此地址，或解码 thunk 中的 jmp [rax+offset]
```

> ⚠ 不同引擎分支（开源 UE5 vs Fortnite 分支）的 vtable 布局可能不同。

### 方法 B：用 GetProcAddress + vtable 搜索（推荐）

在 UEFN 运行时直接确定，最可靠：

```python
# 1. 获取基类实现的导出地址
base_impl = k32.GetProcAddress(engine_h, 
    b"?GetResourceSizeEx@UObject@@UEAAXAEAUFResourceSizeEx@@@Z")

# 2. 获取 UObject CDO 的 vtable
cdo = unreal.Object.static_class().get_default_object()
vtable = read_u64(get_uobject_ptr(cdo))

# 3. 在 vtable 中搜索匹配的 slot
for i in range(200):
    if read_u64(vtable + i * 8) == base_impl:
        print(f"vtable slot = {i}")  # 结果: 69
        break
```

### 验证 slot 正确性

确认子类确实 override 了该 slot：

```python
sm_ptr = get_uobject_ptr(some_static_mesh)
sm_vtable = read_u64(sm_ptr)
sm_func = read_u64(sm_vtable + slot * 8)
assert sm_func != base_impl  # 子类 override → 地址不同
```

---

## 6. 处理复杂 C++ 对象

### 问题

某些 C++ 函数的参数是复杂对象（含 TMap、TArray 等容器），不能简单 memset 为零。

### 解决方案：调用导出的构造函数

```python
SIZEOF = 248  # 通过开源引擎中的 sizeof() 确定

# 分配原始内存
buf = (ctypes.c_uint8 * SIZEOF)()
buf_addr = ctypes.addressof(buf)

# 调用 C++ 构造函数初始化
ctor_addr = k32.GetProcAddress(engine_h, b"??0FResourceSizeEx@@QEAA@...")
Ctor = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint64, ctypes.c_int32)(ctor_addr)
Ctor(buf_addr, 0)  # 正确初始化所有内部容器
```

### 析构与内存泄漏

如果析构函数未导出（shipping build 常见），采用 **重复构造** 策略：

- 每次使用前调用构造函数 → 构造函数会先清理旧状态再初始化
- 最后一次使用后的堆分配不会释放（微量泄漏，可接受）

如果析构函数有导出，直接调用更干净：

```python
dtor_addr = k32.GetProcAddress(engine_h, b"??1ClassName@@QEAA@XZ")
if dtor_addr:
    Dtor = ctypes.CFUNCTYPE(None, ctypes.c_uint64)(dtor_addr)
    Dtor(buf_addr)
```

---

## 7. 确定结构体大小

在开源引擎中编译临时代码输出 sizeof：

```cpp
#include "ProfilingDebugging/ResourceSize.h"
UE_LOG(LogTemp, Display, TEXT("sizeof(FResourceSizeEx) = %llu"), (uint64)sizeof(FResourceSizeEx));
UE_LOG(LogTemp, Display, TEXT("sizeof(TMap<FName,SIZE_T>) = %llu"), (uint64)sizeof(TMap<FName,SIZE_T>));
```

也可以 dump 构造后的原始字节来验证内存布局：

```cpp
FResourceSizeEx Res(EResourceSizeMode::Exclusive);
uint8* Base = reinterpret_cast<uint8*>(&Res);
for (int i = 0; i < sizeof(FResourceSizeEx); i++)
    // 逐字节输出 hex...
```

---

## 8. 完整示例：GetResourceSizeEx 内存审计

将所有步骤组合，对任意 UObject 获取内存占用：

```python
import ctypes
import unreal

# --- 初始化 ---
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetModuleHandleW.restype = ctypes.c_uint64
k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
k32.GetProcAddress.restype = ctypes.c_uint64
k32.GetProcAddress.argtypes = [ctypes.c_uint64, ctypes.c_char_p]

h = k32.GetModuleHandleW("UnrealEditorFortnite-Engine-Win64-Shipping.dll")

ctor_a = k32.GetProcAddress(h, b"??0FResourceSizeEx@@QEAA@W4Type@EResourceSizeMode@@@Z")
gt_a   = k32.GetProcAddress(h, b"?GetTotalMemoryBytes@FResourceSizeEx@@QEBA_KXZ")
base_a = k32.GetProcAddress(h, b"?GetResourceSizeEx@UObject@@UEAAXAEAUFResourceSizeEx@@@Z")

Ctor     = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint64, ctypes.c_int32)(ctor_a)
GetTotal = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint64)(gt_a)
VCall    = ctypes.CFUNCTYPE(None, ctypes.c_uint64, ctypes.c_uint64)

# --- 动态确定 vtable slot ---
cdo = unreal.Object.static_class().get_default_object()
cdo_ptr = ctypes.c_uint64.from_address(id(cdo) + 16).value
vtable = ctypes.c_uint64.from_address(cdo_ptr).value
SLOT = next(i for i in range(200) if ctypes.c_uint64.from_address(vtable + i*8).value == base_a)

# --- 调用 ---
SIZEOF = 248
buf = (ctypes.c_uint8 * SIZEOF)()
buf_addr = ctypes.addressof(buf)

def get_memory_size(obj, mode=0):
    """对任意 UObject 返回资源内存大小。mode: 0=Exclusive, 1=EstimatedTotal"""
    ptr = ctypes.c_uint64.from_address(id(obj) + 16).value
    vt = ctypes.c_uint64.from_address(ptr).value
    vf = ctypes.c_uint64.from_address(vt + SLOT * 8).value
    
    Ctor(buf_addr, mode)
    VCall(vf)(ptr, buf_addr)
    return GetTotal(buf_addr)

# --- 使用 ---
for obj in unreal.ObjectIterator(unreal.StaticMesh):
    if obj is None:
        continue
    size = get_memory_size(obj, mode=0)
    print(f"{obj.get_name()}: {size} bytes")
```

---

## 9. 故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| `GetModuleHandleW` 返回负数 | `restype` 未设为 `c_uint64` | 设置 `k32.GetModuleHandleW.restype = ctypes.c_uint64` |
| `GetProcAddress` 返回 0 | 符号名错误或未导出 | 用 PE 导出表搜索确认符号名；shipping build 可能不导出非 API 函数 |
| vtable slot 不匹配 | 引擎分支不同 | 用方法 B（GetProcAddress + vtable 搜索）在运行时确定 |
| 调用后 buffer 全零 | 未正确构造对象 | 用导出的构造函数初始化，不要 memset 为零 |
| Access violation | 读取无效地址或函数签名错误 | 检查指针有效性；确认 CFUNCTYPE 参数个数和类型正确 |
| 调用结果不正确 | 调用了基类实现而非虚重写 | 通过 vtable 做虚调用，不要直接调用导出的基类函数 |
| editor 崩溃 | PE 导出表遍历触发 page fault | 避免大范围内存扫描；优先用 `GetProcAddress` |

---

## 10. 适用范围

此方法可用于调用任何满足以下条件的 C++ 函数：

1. **函数地址可获取**：通过 DLL 导出符号（`XX_API` 标记）、vtable slot、或从其他已知函数的反汇编中提取
2. **参数可构造**：POD 类型直接构造；复杂类型需调用导出的构造函数
3. **调用约定已知**：Windows x64 统一使用 Microsoft x64 calling convention

已验证的函数类型：
- ✓ 虚成员函数（通过 vtable 调用）
- ✓ 非虚成员函数（通过导出符号直接调用）
- ✓ C++ 构造函数
- ✓ const 成员函数
- ✓ 返回 `SIZE_T`、`void`、指针的函数
