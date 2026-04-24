# 世界征服者4 存档研究记录与编辑器

这个项目记录对 Microsoft Store 版《世界征服者4》 World Conqueror 4（UWP版）本地存档的研究成果，以及一个只编辑已验证字段的小型命令行编辑器。

## 存档位置

Microsoft Store 版存档目录：

```text
C:\Users\<YourUserName>\AppData\Local\Packages\EasyTech.WorldConqueror4_<PackageIdentifier>\LocalState
```

关键文件：

```text
headquarter.sav  总部长期数据
headquarter.bak  总部长期数据备份，通常需要和 sav 同步
prd.sav          身份/产品相关数据
uuid.sav         明文 UUID
settings.cfg     二进制设置文件
campaign.sav     战役进度
conquest*.sav    征服/局内存档
```

## 已确认格式

`headquarter.sav` / `headquarter.bak` 结构：

```text
0x00-0x03  YSAE
0x04-0x07  版本，目前看到为 1
0x08-0x0B  payload 长度，uint32 little-endian
0x0C-0x1B  MD5 校验
0x1C-末尾  Protobuf 风格 payload
```

校验算法：

```text
MD5(payload + b"wc4hq")
```

其中 `payload` 从 offset `0x1C` 开始，到文件末尾结束。`wc4hq` 是从 `WorldConqueror4.exe` 中确认到的 5 字节盐。

注意：只改资源值但不重算 MD5，会导致游戏判定存档无效并重置。

## 已确认字段

以下字段都在 `headquarter.sav` 的顶层 `field 1` 嵌套 Protobuf 块里。

```text
field4   resource4  金币资源
field5   resource5  齿轮资源
field6   resource6  紫色资源
field7   resource7  科技点资源
field8   resource8  勋章资源
field21  resource21 令牌资源
```

已经实测过：

```text
field8  从 809176 改回 809501，重算校验后游戏正常读取
field21 通过游戏内领取从 0 变成 10，差分确认
field21 从 10 改成 1000，修正嵌套长度和校验后游戏正常读取
```

重要教训：

```text
如果新值的 varint 编码长度改变，不仅要更新总 payload 长度，还要更新外层 field1 的嵌套长度。
```

## 编辑器用法

脚本：

```text
wc4_save_editor.py
```

查看当前已知字段：

```powershell
python .\wc4_save_editor.py show
```

设置字段：

```powershell
python .\wc4_save_editor.py set resource21 1000
python .\wc4_save_editor.py set token 1000
python .\wc4_save_editor.py set medal 900000
python .\wc4_save_editor.py set resource4 999999
```

字段别名：

```text
medal -> resource8
token -> resource21
gold -> resource4
gear -> resource5
purple -> resource6
tech / science -> resource7
```

编辑器会自动：

```text
备份 headquarter.sav 和 headquarter.bak
同步修改 sav 和 bak
修正 field1 嵌套长度
修正 payload 长度
重算 MD5(payload + "wc4hq")
```

默认备份目录：

```text
当前工作目录\wc4_save_backups
```

## 安全流程

建议每次编辑前：

```text
1. 退出游戏。
2. 确认没有主游戏窗口在运行。
3. 运行 show 看当前字段。
4. 运行 set 修改一个字段。
5. 进游戏确认结果。
```

如果读档异常，优先恢复编辑器自动生成的备份。

## 后续研究方向

可以继续用“游戏内做一个明确变化 -> 对比前后存档”的方式确认更多字段，例如：

```text
将领列表
科技等级
奇观状态
战役进度
道具/物品数量
```

不要直接猜字段写入正式存档。先做差分，再加入编辑器。
