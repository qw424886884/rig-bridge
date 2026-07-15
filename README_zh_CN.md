# Humanoid Remap Studio / 人形动作重映射工作台

[English](README.md)

Humanoid Remap Studio 是一个 Blender 人形动作自动重映射插件。插件优先识别已知骨架规范；没有命中预设时，会根据语义名称、骨骼层级、身体几何、静止姿态、左右结构和身体前向继续判断。

## 主要功能

- 自动识别动作骨架和目标骨架
- 预设优先，无名称结构识别回退
- 通过左右肢体、躯干终点、脚趾和完整手指链识别匿名骨架
- 单动作和集合批量重映射
- 根位移动作与原地动作
- 静止姿态和身体前向门禁
- 批量失败自动清理，生成 Action 可保存重开
- 安装 Auto-Rig Pro 后可使用优化的 FK 路线

## 使用要求

- Blender 5.1 或更高版本
- 通用流程需要两套有效人形骨架
- Auto-Rig Pro 是可选兼容项，不包含在本插件内

## 安装

当前投稿版本可从 [Blender Extensions 审核页面](https://extensions.blender.org/approval-queue/humanoid-remap-studio/) 下载。官方目录审核完成前，请下载 ZIP 后在 Blender 的“获取扩展”菜单中选择“从磁盘安装”；审核通过后即可在 Blender 扩展目录中直接搜索。

## 快速开始

1. 在 3D 视图侧边栏打开独立的“重映射”标签。
2. 选择单个动作骨架，或选择包含多个动作骨架的集合。
3. 选择目标人形骨架。
4. 点击“自动识别”。
5. 根据需要选择“原地动作”。
6. 点击“执行重映射”或“执行批量”。

需要重新测试时，可以先使用“清除结果”删除插件生成的 Action。

![四步动作重映射流程](media/humanoid-remap-studio-workflow.png)

## 隐私与权限

插件不申请网络、文件、剪贴板、摄像头或麦克风权限。

## Auto-Rig Pro 兼容说明

通用重映射流程不依赖第三方插件。检测到已安装的 Auto-Rig Pro 和兼容目标时，可以调用其运行时 operator 执行优化 FK 烘焙。本仓库和安装包不包含 Auto-Rig Pro 文件或源码。

## 作者与社交账号

- **B站账号：** [帧给你你来K](https://space.bilibili.com/28424547/)
- **账号介绍：** 老王和小C从真实三维问题出发，用 AI 把排查、验证和修复沉淀成可复用流程。

本项目只公开这一条社交主页。

## 许可证

Humanoid Remap Studio 使用 GNU General Public License v3.0 or later，详见 [LICENSE](LICENSE)。
