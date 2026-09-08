# Conow Local — 寄存器与 HA 实体对照表

> **Excel 表格：** [register-map.xlsx](register-map.xlsx)（推荐，含颜色标注实现状态）  
> CSV 备份：[register-map.csv](register-map.csv)

对照协议：[developer-docs/modbus/balcony-solar-storage.md](../../developer-docs/modbus/balcony-solar-storage.md)  
代码来源：`custom_components/conow_local/register_map.py`

## 设计原则

**一个 `地址_hex` = 一个寄存器槽位；`name` 是该地址承载的逻辑含义。**

同一地址可以对应多行 `name`，表示**寄存器值的不同解读方式**，例如：

| 地址_hex | 解读方式 | 示例 name |
|----------|----------|-----------|
| 0x2710 | 位域（bitmask） | `standby` / `running` / `charging` … |
| 0x2779 | 枚举写入值 | `idle`(0) / `force_charge`(1) / `force_discharge`(2) |
| 0x2777 | 开关量 | `off_grid_output_switch`：0=关，1=开 |

uint32 字段占两个连续 16 位寄存器，**仍以起始地址为一个 name**（如 `0x2717` = 电池累计充电电量），占用的 10008 等低位不单独成行。

## 摘要

| 范围 | 说明 |
|------|------|
| 监测 10000–10036 | `register_map` 已全部轮询 |
| 控制 10100–10107 | HA 实体已全部实现 |

### ⚠️ 未实现 / 部分实现

| 状态 | 地址_hex | 说明 |
|------|----------|------|
| 部分 | 0x2710 | `system_status` 原始 uint16 未暴露独立 sensor，仅 bit0–4 的 binary_sensor |
| 未实现 | 0x2710 | bit5–15 协议 Reserved，未暴露 |

---

完整明细见 **register-map.xlsx**。
