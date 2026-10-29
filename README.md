# winffmpeg

在 Windows 中，将每个视频目录内的多段视频转换并合并为一个 MP4。
默认输出 **25P**：每秒 25 帧、逐行扫描。

## 运行条件

- Windows 10/11。
- Python 3.11 或更高版本。安装时启用 `Add Python to PATH`。
- FFmpeg 6.1 或更高版本。构建必须包含 `libx264`、`aac` 和 `bwdif`。
- 将 `ffmpeg.exe` 和 `ffprobe.exe` 所在的 `bin` 目录加入 `PATH`。
- 为输出和中间文件预留磁盘空间。中间音频使用未压缩 PCM，每小时约 0.69 GB。

程序只使用 Python 标准库。不需要执行 `pip install`。

在新终端中检查依赖：

```bat
python --version
ffmpeg -version
ffprobe -version
```

也可以使用 `py -3 --version` 检查 Python。

## 目录结构

```text
winffmpeg/
├── convert_videos.cmd
├── convert_videos.py
└── video/
    ├── 活动A/
    │   ├── 001.mov
    │   ├── 003.avi
    │   └── 子目录/
    │       └── 002.mts
    ├── 活动B/
    │   ├── 001.mp4
    │   └── 002.mxf
    └── output/             ← 程序自动创建
        ├── 活动A.mp4
        └── 活动B.mp4
```

每个第一层子目录是一组。程序递归收集该组内的视频。
`video` 根目录内的单个视频不参与合并。`output` 目录不参与扫描。
空目录和非视频文件会跳过。符号链接与 Windows 目录联接不会跟随。

### 合并顺序

**先比较文件名，按不区分大小写的字典序升序合并。不要按数字自然排序。**

```text
001.mp4 → 002.mp4 → 010.mp4
clip1.mp4 → clip10.mp4 → clip2.mp4
```

不同子目录内的同名文件，再按相对路径字典序升序排序。
排序不使用 Windows 区域语言的拼音规则。中文名称按 Unicode 字符顺序比较。
建议使用补零编号，明确片段顺序，例如 `001`、`002`、`010`。

## 操作步骤

1. 将源视频放入 `video` 的第一层子目录。
2. 在程序目录打开 PowerShell 或命令提示符。
3. 执行默认转换。

```bat
.\convert_videos.cmd
```

启动器默认读取自身所在目录的 `video`，不受终端当前目录影响。
直接运行 Python 时，默认 `video` 相对于终端当前目录。

### 设置帧率

输出 50P，可以保留 50 场隔行素材中的更多运动时刻：

```bat
.\convert_videos.cmd --fps 50
```

支持分数帧率，例如约 29.97 帧/秒：

```bat
.\convert_videos.cmd --fps 30000/1001
```

### 指定输入目录

```bat
.\convert_videos.cmd --input "D:\素材\video" --fps 25
```

输出始终位于指定输入目录的 `output` 子目录。
本地素材目录若叫 `videos`，请显式使用 `--input videos`。

### 指定 FFmpeg 路径

如果未配置 `PATH`，请同时指定两个程序：

```bat
.\convert_videos.cmd --ffmpeg "C:\ffmpeg\bin\ffmpeg.exe" --ffprobe "C:\ffmpeg\bin\ffprobe.exe"
```

### 覆盖已有输出

**警告：此选项会在转换成功后替换同名输出。**

```bat
.\convert_videos.cmd --overwrite
```

默认拒绝覆盖。源视频不修改。
程序先写入 `output` 内的临时目录，成功后才发布最终 MP4。
失败时保留已有输出，并清理临时目录。
中断进程或断电可能留下 `.winffmpeg-*` 临时目录。确认程序未运行后再删除。
不要让多个程序实例同时处理同一输入目录。

## 运动画面“拉丝”处理

如果运动边缘出现交替横线，源视频通常包含隔行扫描的梳齿。
程序默认使用 `bwdif` 去隔行，再转换到指定帧率。
默认强制处理全部帧，以覆盖隔行标记丢失或错误的源视频。

```text
bwdif=mode=send_field:parity=auto:deint=all → fps=25
```

`send_field` 先为每个场产生逐行帧。`fps` 再转换为目标帧率。
25P 不能保留 50 场/秒素材的全部运动时刻。需要更平滑的运动时，可使用 `--fps 50`。

如果自动识别场序后仍出现运动抖动，请按素材实际场序指定：

```bat
.\convert_videos.cmd --parity tff
.\convert_videos.cmd --parity bff
```

- `tff`：顶场优先。
- `bff`：底场优先。
- `auto`：依赖源视频的场序信息。信息缺失时，FFmpeg 通常按顶场优先处理。

如果素材本身是逐行视频，建议关闭去隔行，避免不必要的垂直细节损失：

```bat
.\convert_videos.cmd --deinterlace off
```

仅处理带隔行标记的帧：

```bat
.\convert_videos.cmd --deinterlace auto
```

`auto` 不会分析画面内容。错误标记为逐行的隔行视频，应使用默认 `force`。
去隔行不能修复所有运动模糊、重影、滚动快门、屏幕撕裂或已缩放烘焙的梳齿。
因此，程序不保证消除所有被称为“拉丝”的画面问题。

## 视频与音频规则

- 输出封装为 MP4，视频使用 H.264，像素格式为 `yuv420p`。
- 视频质量参数为 CRF 18，编码预设为 `medium`。合并时不重复编码视频。
- 同组分辨率采用排序后首段视频的显示尺寸，并调整为偶数尺寸。
- 其他片段保持宽高比缩放，不足部分补黑边。不裁剪画面。
- 音频输出为 AAC、192 kbit/s、48 kHz、双声道。
- 默认只使用第一条音轨，不混合其他音轨。
- 无音轨的片段补静音。音频过短则补静音，过长则按视频时长截断。
- 每段编码后按实际视频帧数确定时长，避免音频尾部改变合并时间线。
- 中间文件使用 NUT，保留精确时间基，避免分数帧率被毫秒取整。
- 不保留字幕、章节、数据流、原始多音轨和大部分源元数据。
- 流程面向常规 SDR 视频。不包含 HDR 色调映射和专业色彩管理。

选择第二条音轨，编号从 0 开始：

```bat
.\convert_videos.cmd --audio-track 1
```

有音轨但不存在指定编号时，该组报错。完全无音轨时，仍补静音。

识别的扩展名如下，大小写不限。实际能否解码取决于 FFmpeg 构建：

```text
.mp4 .m4v .mov .mkv .avi .mts .m2ts .ts .mpeg .mpg .wmv .webm .flv .vob .mxf .3gp
```

FFmpeg 检测到输入或解码错误时，该组失败，不发布部分结果。其他组继续处理。
仅靠解码不能识别所有文件损坏，例如在完整帧边界截短且无可靠时长信息的文件。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 所有已发现的视频组转换成功 |
| `1` | 至少一组失败，或未发现视频组 |
| `2` | 参数、输入目录、工具路径或输出目录配置错误 |

查看全部参数：

```bat
.\convert_videos.cmd --help
```

## GitHub Actions 自动验收

每次 push、pull request 或手动运行时，工作流会自动验收：

- Windows：Python 3.11 和 3.13。
- Linux：Python 3.11，补充跨平台检查。
- 动态生成测试素材，不上传真实源视频。
- 检查递归分组、文件名字典序、顺序画面与混合分辨率。
- 检查 H.264、AAC、25P、50P 和分数帧率。
- 检查无声片段补静音、多音轨选择和音频实际采样值。
- 比较合成运动画面的相邻扫描行像素差，验证去隔行确实减少梳齿。
- 检查中文、空格、单引号和 `&` 路径。
- 检查 Windows `.cmd` 的默认路径、参数透传和退出码。
- 检查覆盖保护、损坏文件、依赖缺失、非法参数与源文件不变。
- 检查符号链接与 Windows 目录联接不会导入外部素材或重定向输出。

工作流会上传验收日志与工具版本，保留 14 天。
测试使用真实 FFmpeg 和 FFprobe，不以模拟调用代替媒体处理。

本地运行相同测试：

```bat
python -m unittest discover -s tests -v
```

测试素材位于系统临时目录，完成后自动清理。Windows 启动器测试只在 Windows 实际执行。
