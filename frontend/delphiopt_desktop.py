from __future__ import annotations

import ctypes
import json
import re
import sys
import threading
import time
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend.app_backend import FrontendBackend  # noqa: E402
from delphiopt.config import merge_config  # noqa: E402


BG, SIDEBAR, PANEL, PANEL_2, LINE = "#080B12", "#0C111B", "#101723", "#151E2D", "#243149"
TEXT, MUTED, CYAN, PURPLE = "#EDF4FF", "#8391A8", "#66E3DD", "#9B8CFF"
GREEN, AMBER, RED = "#65D99A", "#F4C76B", "#F07683"
FONT, MONO = "Microsoft YaHei UI", "Cascadia Mono"


def enable_high_dpi() -> None:
    """Ask Windows for per-monitor rendering before Tk creates its native window."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


class DelphiOptDesktop(tk.Tk):
    def __init__(self) -> None:
        enable_high_dpi()
        super().__init__()
        self.tk.call("tk", "scaling", max(1.0, self.winfo_fpixels("1i") / 72.0))
        self.backend = FrontendBackend()
        self.title("DelphiOpt — 自适应多智能体优化控制台")
        self.geometry("1440x900")
        self.minsize(1180, 760)
        self.configure(bg=BG)
        self.option_add("*Font", (FONT, 10))
        self.project = tk.StringVar(value=str(self.backend.ensure_demo()))
        self.config_path = tk.StringVar()
        self.mode = tk.StringVar(value="Delphi 协作")
        self.scheduler = tk.StringVar(value="自适应 VOI")
        self.budget = tk.DoubleVar(value=1.0)
        self.rounds = tk.IntVar(value=3)
        self.max_tokens = tk.IntVar(value=150000)
        self.max_latency = tk.IntVar(value=900)
        self.max_llm_calls = tk.IntVar(value=30)
        self.max_benchmark_runs = tk.IntVar(value=20)
        self.max_tool_calls = tk.IntVar(value=100)
        self.base_tokens = tk.IntVar(value=900)
        self.scheduler_tool_budget = tk.IntVar(value=2)
        self.seed = tk.IntVar(value=0)
        self.warmups = tk.IntVar(value=2)
        self.repetitions = tk.IntVar(value=5)
        self.benchmark_timeout = tk.IntVar(value=120)
        self.meaningful_speedup = tk.DoubleVar(value=1.05)
        self.disagreement_threshold = tk.DoubleVar(value=0.08)
        self.max_cv = tk.DoubleVar(value=0.15)
        self.marginal_gain = tk.DoubleVar(value=0.02)
        self.min_utility = tk.DoubleVar(value=0.1)
        self.no_improvement_rounds = tk.IntVar(value=2)
        self.minority_bonus = tk.DoubleVar(value=0.12)
        self.sandbox_type = tk.StringVar(value="本地执行")
        self.sandbox_network = tk.BooleanVar(value=False)
        self.cpu_limit = tk.IntVar(value=2)
        self.memory_mb = tk.IntVar(value=2048)
        self.sandbox_image = tk.StringVar(value="python:3.12-slim")
        self.test_command = tk.StringVar(value="pytest -q")
        self.benchmark_command = tk.StringVar(value="python benchmark.py")
        self.lint_command = tk.StringVar(value="")
        self.model_alias = tk.StringVar()
        self.model_protocol = tk.StringVar(value="OpenAI 兼容接口")
        self.model_name = tk.StringVar()
        self.model_endpoint = tk.StringVar(value="https://api.openai.com/v1/chat/completions")
        self.model_api_env = tk.StringVar(value="OPENAI_API_KEY")
        self.model_api_key = tk.StringVar()
        self.model_timeout = tk.DoubleVar(value=120.0)
        self.model_input_price = tk.DoubleVar(value=0.0)
        self.model_output_price = tk.DoubleVar(value=0.0)
        self.model_priority_enabled = tk.BooleanVar(value=False)
        self.model_test_status = tk.StringVar(value="尚未测试连接")
        self.model_profiles: dict[str, dict[str, Any]] = {}
        self.model_priority: list[str] = []
        self.auto_open_report = tk.BooleanVar(value=True)
        self.raw_config: dict[str, Any] | None = None
        self.status_text = tk.StringVar(value="就绪")
        self.page_title = tk.StringVar(value="总览")
        self.metrics: dict[str, tk.Label] = {}
        self.nav: dict[str, tk.Button] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.busy = False
        self._load_preferences()
        self._configure_styles()
        self._build_shell()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.show_page("总览")
        self.refresh_runs()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=36, borderwidth=0, font=(FONT, 10))
        style.map("Treeview", background=[("selected", "#233B51")], foreground=[("selected", TEXT)])
        style.configure("Treeview.Heading", background=PANEL_2, foreground=MUTED, relief="flat", padding=9, font=(FONT, 10, "bold"))
        style.configure("TCombobox", fieldbackground=PANEL_2, background=PANEL_2, foreground=TEXT, arrowcolor=CYAN, font=(FONT, 10))
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", PANEL_2)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", PANEL_2)],
            selectforeground=[("readonly", TEXT)],
        )
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL_2, foreground=MUTED, padding=(16, 10), font=(FONT, 10))
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", CYAN)])

    def _build_shell(self) -> None:
        sidebar = tk.Frame(self, bg=SIDEBAR, width=230)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=SIDEBAR, height=104)
        brand.pack(fill="x")
        tk.Label(brand, text="◈", fg=CYAN, bg=SIDEBAR, font=(FONT, 24, "bold")).place(x=22, y=27)
        tk.Label(brand, text="DELPHIOPT", fg=TEXT, bg=SIDEBAR, font=(FONT, 14, "bold")).place(x=60, y=27)
        tk.Label(brand, text="智能优化控制台", fg=MUTED, bg=SIDEBAR, font=(FONT, 8, "bold")).place(x=61, y=53)
        for name, icon in (
            ("总览", "⌁"), ("优化任务", "↗"), ("基准与实验", "⌬"),
            ("运行与报告", "≡"), ("模型与专家", "◇"), ("高级设置", "⚙"),
        ):
            button = tk.Button(
                sidebar, text=f"  {icon}    {name}", anchor="w", padx=18, pady=13, bd=0,
                bg=SIDEBAR, fg=MUTED, activebackground=PANEL_2, activeforeground=TEXT,
                font=(FONT, 10), cursor="hand2", command=lambda key=name: self.show_page(key),
            )
            button.pack(fill="x", padx=10, pady=2)
            self.nav[name] = button
        tk.Frame(sidebar, bg=SIDEBAR).pack(expand=True)
        status = tk.Frame(sidebar, bg=PANEL, padx=15, pady=14)
        status.pack(fill="x", padx=14, pady=18)
        tk.Label(status, text="运行时状态", bg=PANEL, fg=MUTED, font=(FONT, 8, "bold")).pack(anchor="w")
        row = tk.Frame(status, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        self.status_dot = tk.Label(row, text="●", bg=PANEL, fg=GREEN)
        self.status_dot.pack(side="left")
        tk.Label(row, textvariable=self.status_text, bg=PANEL, fg=TEXT, font=(MONO, 9, "bold")).pack(side="left", padx=7)

        main = tk.Frame(self, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        top = tk.Frame(main, bg=BG, height=78)
        top.pack(fill="x", padx=34)
        top.pack_propagate(False)
        tk.Label(top, textvariable=self.page_title, bg=BG, fg=TEXT, font=(FONT, 20, "bold")).pack(side="left", pady=22)
        self._button(top, "打开项目", self.choose_project).pack(side="right", pady=20)
        self.content = tk.Frame(main, bg=BG)
        self.content.pack(fill="both", expand=True, padx=34, pady=(0, 28))
        self.pages = {
            "总览": self._overview(),
            "优化任务": self._optimize(),
            "基准与实验": self._experiments(),
            "运行与报告": self._runs(),
            "模型与专家": self._catalog(),
            "高级设置": self._settings(),
        }

    def _page(self) -> tk.Frame:
        return tk.Frame(self.content, bg=BG)

    def _label(self, parent: tk.Widget, text: str, *, color: str = MUTED, size: int = 10, bold: bool = False) -> tk.Label:
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color, font=(FONT, max(9, size), "bold" if bold else "normal"))

    def _card(self, parent: tk.Widget) -> tk.Frame:
        return tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)

    def _button(self, parent: tk.Widget, text: str, command: Callable[[], None], *, primary: bool = False) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command, bg=CYAN if primary else PANEL_2, fg=BG if primary else TEXT,
            activebackground="#8AF2EC" if primary else LINE, activeforeground=BG if primary else TEXT,
            bd=0, padx=18, pady=10, font=(FONT, 10, "bold"), cursor="hand2",
        )

    def _entry(self, parent: tk.Widget, variable: tk.Variable, width: int = 28) -> tk.Entry:
        return tk.Entry(
            parent, textvariable=variable, width=width, bg=PANEL_2, fg=TEXT, insertbackground=CYAN,
            relief="flat", highlightbackground=LINE, highlightcolor=CYAN, highlightthickness=1, font=(MONO, 10),
        )

    def _overview(self) -> tk.Frame:
        page = self._page()
        hero = self._card(page)
        hero.pack(fill="x", pady=(0, 18))
        left = tk.Frame(hero, bg=PANEL)
        left.pack(side="left", fill="both", expand=True, padx=26, pady=22)
        self._label(left, "自适应 DELPHI 运行时", color=CYAN, size=9, bold=True).pack(anchor="w")
        self._label(left, "以真实性能证据驱动代码优化", color=TEXT, size=24, bold=True).pack(anchor="w", pady=(8, 3))
        self._label(left, "独立专家 · 匿名反馈 · VOI 调度 · 可验证基准测试").pack(anchor="w")
        self._button(hero, "开始优化", lambda: self.show_page("优化任务"), primary=True).pack(side="right", padx=24)
        metrics = tk.Frame(page, bg=BG)
        metrics.pack(fill="x", pady=(0, 18))
        for index, (key, title, value, accent) in enumerate((
            ("status", "最近决策", "暂无运行", PURPLE), ("speedup", "已验证加速比", "—", CYAN),
            ("correctness", "正确性", "—", GREEN), ("calls", "模型调用次数", "—", AMBER),
        )):
            metrics.grid_columnconfigure(index, weight=1)
            card = self._card(metrics)
            card.grid(row=0, column=index, sticky="nsew", padx=6)
            tk.Frame(card, bg=accent, width=3).pack(side="left", fill="y")
            body = tk.Frame(card, bg=PANEL)
            body.pack(fill="both", expand=True, padx=17, pady=16)
            self._label(body, title, size=8, bold=True).pack(anchor="w")
            label = self._label(body, value, color=TEXT, size=17, bold=True)
            label.pack(anchor="w", pady=(8, 0))
            self.metrics[key] = label
        pipeline = self._card(page)
        pipeline.pack(fill="both", expand=True)
        self._label(pipeline, "决策流水线", color=TEXT, size=11, bold=True).pack(anchor="w", padx=22, pady=(18, 14))
        track = tk.Frame(pipeline, bg=PANEL)
        track.pack(fill="x", padx=22)
        stages = ("分析", "征询", "聚合", "调度", "补丁", "验证", "决策")
        for index, stage in enumerate(stages):
            box = tk.Frame(track, bg=PANEL_2, highlightbackground=LINE, highlightthickness=1)
            box.pack(side="left", fill="x", expand=True)
            self._label(box, f"{index + 1:02}", color=CYAN, size=8, bold=True).pack(pady=(13, 3))
            self._label(box, stage, color=TEXT, size=8, bold=True).pack(pady=(0, 13))
            if index < len(stages) - 1:
                self._label(track, "›", size=18).pack(side="left", padx=6)
        self._label(pipeline, "只有通过正确性检查与重复基准测试证据门槛的补丁才会被接受。").pack(anchor="w", padx=22, pady=22)
        return page

    def _project_selector(self, parent: tk.Widget) -> None:
        row = tk.Frame(parent, bg=parent.cget("bg"))
        row.pack(fill="x", pady=(0, 16))
        self._label(row, "项目目录", size=8, bold=True).pack(anchor="w")
        line = tk.Frame(row, bg=parent.cget("bg"))
        line.pack(fill="x", pady=(6, 0))
        self._entry(line, self.project, 80).pack(side="left", fill="x", expand=True, ipady=8)
        self._button(line, "浏览", self.choose_project).pack(side="left", padx=(10, 0))

    def _console(self, parent: tk.Widget, height: int = 18) -> tk.Text:
        frame = self._card(parent)
        frame.pack(fill="both", expand=True)
        head = tk.Frame(frame, bg=PANEL_2)
        head.pack(fill="x")
        self._label(head, "实时输出", color=TEXT, size=8, bold=True).pack(side="left", padx=14, pady=9)
        self._button(head, "复制", lambda: self.copy_console(text)).pack(side="right", padx=(0, 8), pady=4)
        self._button(head, "清空", lambda: self.clear_console(text)).pack(side="right", padx=8, pady=4)
        text = tk.Text(frame, height=height, bg="#090E17", fg="#B7C6DA", insertbackground=CYAN, relief="flat",
                       padx=16, pady=14, font=(MONO, 9), wrap="word")
        text.pack(fill="both", expand=True)
        text.insert("end", "DelphiOpt 运行时已就绪。\n")
        text.configure(state="disabled")
        return text

    def _optimize(self) -> tk.Frame:
        page = self._page()
        form = self._card(page)
        form.pack(fill="x", pady=(0, 14))
        body = tk.Frame(form, bg=PANEL)
        body.pack(fill="x", padx=24, pady=20)
        body.grid_columnconfigure(1, weight=1)

        self._label(body, "项目目录", color=TEXT, size=9, bold=True).grid(row=0, column=0, sticky="w", pady=(0, 8))
        project_entry = self._entry(body, self.project, 70)
        project_entry.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 10), ipady=8)
        self._button(body, "浏览项目", self.choose_project).grid(row=1, column=2, sticky="e")

        self._label(body, "配置文件（可选）", color=TEXT, size=9, bold=True).grid(row=2, column=0, sticky="w", pady=(18, 8))
        config_entry = self._entry(body, self.config_path, 70)
        config_entry.grid(row=3, column=0, columnspan=2, sticky="ew", padx=(0, 10), ipady=8)
        self._button(body, "选择配置", self.choose_config).grid(row=3, column=2, sticky="e")

        parameters = self._card(page)
        parameters.pack(fill="x", pady=(0, 14))
        self._label(parameters, "运行参数", color=TEXT, size=11, bold=True).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=22, pady=(17, 8)
        )
        controls: tuple[tuple[str, tk.Variable, tuple[str, ...] | None], ...] = (
            ("协作模式", self.mode, ("单智能体", "Best-of-N", "直接辩论", "Delphi 协作")),
            ("调度策略", self.scheduler, ("固定调度", "难度路由", "自适应 VOI")),
            ("费用预算（美元）", self.budget, None),
            ("最大轮数", self.rounds, None),
        )
        for column, (title, variable, choices) in enumerate(controls):
            parameters.grid_columnconfigure(column, weight=1, uniform="optimize")
            cell = tk.Frame(parameters, bg=PANEL)
            cell.grid(row=1, column=column, sticky="ew", padx=(22 if column == 0 else 8, 22 if column == 3 else 8), pady=(4, 16))
            self._label(cell, title, size=8, bold=True).pack(anchor="w", pady=(0, 7))
            control: tk.Widget
            if choices:
                control = ttk.Combobox(cell, textvariable=variable, values=choices, state="readonly")
            else:
                control = self._entry(cell, variable)
            control.pack(fill="x", ipady=7)

        actions = tk.Frame(parameters, bg=PANEL)
        actions.grid(row=2, column=0, columnspan=4, sticky="ew", padx=22, pady=(0, 18))
        self._label(actions, "建议先执行项目预检，再启动优化任务。", size=9).pack(side="left")
        self._button(actions, "运行优化", self.launch_optimize, primary=True).pack(side="right", padx=(8, 0))
        self._button(actions, "项目预检", self.preflight_project).pack(side="right")
        self.optimize_layout_columns = 4
        self.optimize_console = self._console(page)
        return page

    def _experiments(self) -> tk.Frame:
        page = self._page()
        top = tk.Frame(page, bg=BG)
        top.pack(fill="x", pady=(0, 14))
        cards = (
            ("基准测试", "执行正确性门禁与多次统计性能测量。", CYAN, self.launch_benchmark, "运行基准"),
            ("18 组消融实验", "专家组合 × 协作模式 × 调度策略，使用真实模拟服务商运行。", PURPLE, self.launch_ablation, "运行完整实验"),
            ("实验报告", "查看成本、加速比、多样性、信誉与收敛图表。", GREEN, self.open_ablation_report, "打开报告"),
        )
        for index, (title, copy, accent, command, action) in enumerate(cards):
            top.grid_columnconfigure(index, weight=1)
            card = self._card(top)
            card.grid(row=0, column=index, sticky="nsew", padx=7)
            tk.Frame(card, bg=accent, height=3).pack(fill="x")
            self._label(card, title, color=TEXT, size=14, bold=True).pack(anchor="w", padx=18, pady=(17, 7))
            label = self._label(card, copy, size=9)
            label.configure(wraplength=290, justify="left")
            label.pack(anchor="w", padx=18)
            self._button(card, action, command).pack(anchor="w", padx=18, pady=18)
        selector = self._card(page)
        selector.pack(fill="x", pady=(0, 14))
        inside = tk.Frame(selector, bg=PANEL)
        inside.pack(fill="x", padx=20, pady=14)
        self._project_selector(inside)
        self.experiment_console = self._console(page)
        return page

    def _runs(self) -> tk.Frame:
        page = self._page()
        toolbar = tk.Frame(page, bg=BG)
        toolbar.pack(fill="x", pady=(0, 12))
        for text, command, primary in (
            ("刷新", self.refresh_runs, False), ("查看追踪", self.inspect_selected, False),
            ("生成报告", self.report_selected, True), ("导出摘要", self.export_selected_summary, False),
            ("复现实验", self.reproduce_selected, False),
        ):
            self._button(toolbar, text, command, primary=primary).pack(side="left", padx=(0, 8))
        self._button(toolbar, "打开运行目录", self.open_runs_folder).pack(side="left", padx=(0, 8))
        tk.Checkbutton(
            toolbar, text="生成后自动打开报告", variable=self.auto_open_report, bg=BG, fg=MUTED,
            activebackground=BG, activeforeground=TEXT, selectcolor=PANEL_2,
        ).pack(side="left")
        self._label(toolbar, "从当前项目的 .delphiopt/runs 读取运行记录。").pack(side="right")
        table_frame = self._card(page)
        table_frame.pack(fill="both", expand=True)
        columns = ("run", "status", "speedup", "correctness", "cost", "tokens", "rounds")
        self.run_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        labels = ("运行标识", "状态", "加速比", "正确性", "费用（美元）", "令牌数", "轮数")
        widths = (250, 100, 100, 100, 100, 110, 80)
        for column, label, width in zip(columns, labels, widths):
            self.run_tree.heading(column, text=label)
            self.run_tree.column(column, width=width, anchor="w")
        self.run_tree.pack(fill="both", expand=True, padx=1, pady=1)
        self.run_console = self._console(page, height=9)
        self.run_console.master.pack_configure(pady=(14, 0))
        return page

    def _catalog(self) -> tk.Frame:
        page = self._page()
        top = tk.Frame(page, bg=BG)
        top.pack(fill="x", pady=(0, 12))
        self._button(top, "加载模型", self.load_models, primary=True).pack(side="left")
        self._button(top, "加载专家", self.load_experts).pack(side="left", padx=8)
        self._label(top, "从当前 DelphiOpt 配置解析。").pack(side="right")
        self.catalog_console = self._console(page, height=30)
        return page

    def _settings(self) -> tk.Frame:
        page = self._page()
        toolbar = tk.Frame(page, bg=BG)
        toolbar.pack(fill="x", pady=(0, 12))
        self._button(toolbar, "经济预设", lambda: self.apply_preset("economy")).pack(side="left", padx=(0, 8))
        self._button(toolbar, "均衡预设", lambda: self.apply_preset("balanced"), primary=True).pack(side="left", padx=(0, 8))
        self._button(toolbar, "深度预设", lambda: self.apply_preset("deep")).pack(side="left", padx=(0, 8))
        self._button(toolbar, "载入配置", self.load_settings_file).pack(side="right", padx=(8, 0))
        self._button(toolbar, "保存配置", self.save_settings_file).pack(side="right", padx=(8, 0))
        self._button(toolbar, "验证配置", self.validate_current_settings).pack(side="right")

        notebook = ttk.Notebook(page)
        self.settings_notebook = notebook
        notebook.pack(fill="both", expand=True)
        budget_tab = tk.Frame(notebook, bg=PANEL)
        benchmark_tab = tk.Frame(notebook, bg=PANEL)
        delphi_tab = tk.Frame(notebook, bg=PANEL)
        sandbox_tab = tk.Frame(notebook, bg=PANEL)
        model_tab = tk.Frame(notebook, bg=PANEL)
        provider_tab = tk.Frame(notebook, bg=PANEL)
        raw_tab = tk.Frame(notebook, bg=PANEL)
        for tab, title in (
            (budget_tab, "预算与调度"), (benchmark_tab, "基准测试"), (delphi_tab, "Delphi 策略"),
            (sandbox_tab, "沙箱与项目"), (model_tab, "模型接入"),
            (provider_tab, "系统诊断"), (raw_tab, "高级 YAML"),
        ):
            notebook.add(tab, text=title)

        self._settings_grid(budget_tab, (
            ("最大费用（美元）", self.budget), ("最大令牌数", self.max_tokens), ("最大延迟（秒）", self.max_latency),
            ("最大模型调用", self.max_llm_calls), ("最大基准次数", self.max_benchmark_runs), ("最大工具调用", self.max_tool_calls),
            ("单轮基础令牌数", self.base_tokens), ("单轮工具预算", self.scheduler_tool_budget), ("随机种子", self.seed),
        ))
        self._settings_grid(benchmark_tab, (
            ("预热次数", self.warmups), ("重复次数", self.repetitions), ("超时（秒）", self.benchmark_timeout),
            ("有意义加速阈值", self.meaningful_speedup), ("最大变异系数", self.max_cv),
        ))
        self._settings_grid(delphi_tab, (
            ("最大 Delphi 轮数", self.rounds), ("分歧阈值", self.disagreement_threshold),
            ("边际收益阈值", self.marginal_gain), ("最低效用/美元", self.min_utility),
            ("无改进停止轮数", self.no_improvement_rounds), ("少数派奖励", self.minority_bonus),
        ))

        sandbox_body = tk.Frame(sandbox_tab, bg=PANEL)
        sandbox_body.pack(fill="both", expand=True, padx=22, pady=20)
        select_row = tk.Frame(sandbox_body, bg=PANEL)
        select_row.pack(fill="x", pady=(0, 14))
        self._label(select_row, "沙箱类型", color=TEXT, bold=True).pack(side="left")
        ttk.Combobox(select_row, textvariable=self.sandbox_type, values=("本地执行", "Docker 容器"), state="readonly", width=18).pack(side="left", padx=12)
        tk.Checkbutton(
            select_row, text="允许网络访问", variable=self.sandbox_network, bg=PANEL, fg=TEXT,
            activebackground=PANEL, activeforeground=TEXT, selectcolor=PANEL_2,
        ).pack(side="left", padx=18)
        self._settings_grid(sandbox_body, (
            ("处理器核心限额", self.cpu_limit), ("内存限额（MB）", self.memory_mb), ("Docker 镜像", self.sandbox_image),
            ("测试命令", self.test_command), ("基准命令", self.benchmark_command), ("可选代码检查命令", self.lint_command),
        ), packed=False)

        self._build_model_settings(model_tab)

        provider_body = tk.Frame(provider_tab, bg=PANEL)
        provider_body.pack(fill="both", expand=True, padx=22, pady=18)
        self.provider_rows = tk.Frame(provider_body, bg=PANEL)
        self.provider_rows.pack(fill="x")
        self.refresh_diagnostics()
        buttons = tk.Frame(provider_body, bg=PANEL)
        buttons.pack(fill="x", pady=18)
        self._button(buttons, "刷新诊断", self.refresh_diagnostics).pack(side="left")
        root = Path(__file__).resolve().parents[1]
        for text, path in (
            ("打开应用目录", self.backend.app_home), ("打开 README", root / "README.md"),
            ("打开默认配置", root / "configs" / "default.yaml"), ("打开文档目录", root / "docs"),
        ):
            self._button(buttons, text, lambda value=path: self.backend.open_path(value)).pack(side="left", padx=(8, 0))
        self._label(provider_body, "密钥只从环境变量读取，桌面端不会保存任何凭据。").pack(anchor="w")

        raw_header = tk.Frame(raw_tab, bg=PANEL)
        raw_header.pack(fill="x", padx=18, pady=(16, 8))
        self._label(raw_header, "可直接编辑模型、专家角色、候选评分权重及任意高级字段。", color=TEXT).pack(side="left")
        self._button(raw_header, "从表单生成", self.form_to_yaml).pack(side="right")
        self._button(raw_header, "应用 YAML", self.yaml_to_form, primary=True).pack(side="right", padx=8)
        self.raw_yaml = tk.Text(raw_tab, bg="#090E17", fg="#B7C6DA", insertbackground=CYAN, relief="flat", font=(MONO, 9), padx=14, pady=12)
        self.raw_yaml.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        initial_path = Path(self.config_path.get()) if self.config_path.get() and Path(self.config_path.get()).is_file() else None
        self._apply_settings(self.backend.load_settings(initial_path))
        self.form_to_yaml()
        return page

    def _build_model_settings(self, parent: tk.Frame) -> None:
        container = tk.Frame(parent, bg=PANEL)
        container.pack(fill="both", expand=True, padx=18, pady=16)
        # Keep the priority table wide enough to show every identifying field;
        # the editor receives the remaining space and remains responsive.
        container.grid_columnconfigure(0, weight=2, minsize=410)
        container.grid_columnconfigure(1, weight=3, minsize=460)
        container.grid_rowconfigure(1, weight=1)

        self._label(container, "模型优先级（从上到下）", color=TEXT, bold=True).grid(row=0, column=0, sticky="w", pady=(0, 8))
        priority_toggle = tk.Checkbutton(
            container, text="启用自定义优先级与故障转移", variable=self.model_priority_enabled,
            bg=PANEL, fg=TEXT, activebackground=PANEL, activeforeground=TEXT, selectcolor=PANEL_2,
        )
        priority_toggle.grid(row=0, column=1, sticky="e", pady=(0, 8))

        list_panel = tk.Frame(container, bg=PANEL_2, highlightbackground=LINE, highlightthickness=1)
        list_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        columns = ("priority", "alias", "protocol", "model")
        self.model_tree = ttk.Treeview(list_panel, columns=columns, show="headings", selectmode="browse", height=13)
        for column, title, width in (
            ("priority", "优先级", 55), ("alias", "配置名称", 95),
            ("protocol", "接口协议", 105), ("model", "模型名称", 135),
        ):
            self.model_tree.heading(column, text=title)
            self.model_tree.column(column, width=width, anchor="w")
        self.model_tree.pack(fill="both", expand=True, padx=1, pady=1)
        self.model_tree.bind("<<TreeviewSelect>>", self.load_selected_model)

        order_bar = tk.Frame(container, bg=PANEL)
        order_bar.grid(row=2, column=0, sticky="ew", pady=(10, 0), padx=(0, 12))
        self._button(order_bar, "上移", lambda: self.move_model(-1)).pack(side="left")
        self._button(order_bar, "下移", lambda: self.move_model(1)).pack(side="left", padx=8)
        self._button(order_bar, "删除", self.delete_model).pack(side="left")

        editor = tk.Frame(container, bg=PANEL_2, highlightbackground=LINE, highlightthickness=1)
        editor.grid(row=1, column=1, rowspan=2, sticky="nsew")
        editor.grid_columnconfigure(0, weight=1)
        editor.grid_columnconfigure(1, weight=1)
        editor.grid_columnconfigure(2, weight=1)
        editor_header = tk.Frame(editor, bg=PANEL_2)
        editor_header.grid(row=0, column=0, columnspan=3, sticky="ew", padx=16, pady=(10, 4))
        self._label(editor_header, "接入或修改模型", color=TEXT, size=11, bold=True).pack(side="left")
        self._button(editor_header, "清空", self.clear_model_form).pack(side="right")
        self._button(editor_header, "测试连接", self.test_model_connection).pack(side="right", padx=7)
        self._button(editor_header, "保存模型", self.upsert_model, primary=True).pack(side="right")
        tk.Label(
            editor, textvariable=self.model_test_status, bg=PANEL_2, fg=CYAN,
            font=(FONT, 9), justify="left", anchor="w", wraplength=420,
        ).grid(row=1, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 2))
        row = 2
        protocol_cell = tk.Frame(editor, bg=PANEL_2)
        protocol_cell.grid(row=row, column=0, columnspan=3, sticky="ew", padx=16, pady=4)
        self._label(protocol_cell, "接口协议", size=8, bold=True).pack(anchor="w", pady=(0, 5))
        protocol = ttk.Combobox(
            protocol_cell, textvariable=self.model_protocol,
            values=("OpenAI 兼容接口", "OpenAI", "Anthropic", "Gemini", "模拟测试"), state="readonly",
        )
        protocol.pack(fill="x", ipady=5)
        protocol.bind("<<ComboboxSelected>>", self.model_protocol_changed)
        row += 1

        def field(row_number: int, column: int, title: str, variable: tk.Variable, columnspan: int = 1) -> None:
            cell = tk.Frame(editor, bg=PANEL_2)
            left = 16 if column == 0 else 5
            right = 16 if column + columnspan == 3 else 5
            cell.grid(
                row=row_number, column=column, columnspan=columnspan, sticky="ew",
                padx=(left, right), pady=4,
            )
            self._label(cell, title, size=8, bold=True).pack(anchor="w", pady=(0, 5))
            self._entry(cell, variable, 24).pack(fill="x", ipady=6)

        field(row, 0, "配置名称", self.model_alias)
        field(row, 1, "模型名称", self.model_name, 2)
        row += 1
        field(row, 0, "接口地址", self.model_endpoint, 2)
        field(row, 2, "密钥环境变量", self.model_api_env)
        row += 1
        field(row, 0, "超时（秒）", self.model_timeout)
        field(row, 1, "输入价格/百万令牌", self.model_input_price)
        field(row, 2, "输出价格/百万令牌", self.model_output_price)
        row += 1
        key_cell = tk.Frame(editor, bg=PANEL_2)
        key_cell.grid(row=row, column=0, columnspan=3, sticky="ew", padx=16, pady=4)
        self._label(key_cell, "API 密钥（仅保留在当前进程内）", size=8, bold=True).pack(anchor="w", pady=(0, 5))
        key_entry = self._entry(key_cell, self.model_api_key, 40)
        key_entry.configure(show="●")
        key_entry.pack(fill="x", ipady=6)

    def _settings_grid(self, parent: tk.Widget, fields: tuple[tuple[str, tk.Variable], ...], *, packed: bool = True) -> None:
        body = tk.Frame(parent, bg=PANEL)
        if packed:
            body.pack(fill="both", expand=True, padx=22, pady=20)
        else:
            body.pack(fill="x")
        for index, (label, variable) in enumerate(fields):
            row, column = divmod(index, 3)
            body.grid_columnconfigure(column, weight=1)
            cell = tk.Frame(body, bg=PANEL)
            cell.grid(row=row, column=column, sticky="ew", padx=8, pady=9)
            self._label(cell, label, color=TEXT, size=9, bold=True).pack(anchor="w", pady=(0, 6))
            self._entry(cell, variable, 24).pack(fill="x", ipady=7)

    @staticmethod
    def _mode_value(display: str) -> str:
        return {"单智能体": "single", "Best-of-N": "best_of_n", "直接辩论": "debate", "Delphi 协作": "delphi"}.get(display, display)

    @staticmethod
    def _scheduler_value(display: str) -> str:
        return {"固定调度": "fixed", "难度路由": "difficulty", "自适应 VOI": "adaptive_voi"}.get(display, display)

    @staticmethod
    def _sandbox_value(display: str) -> str:
        return {"本地执行": "local", "Docker 容器": "docker"}.get(display, display)

    @staticmethod
    def _protocol_value(display: str) -> str:
        return {
            "OpenAI 兼容接口": "openai-compatible", "OpenAI": "openai",
            "Anthropic": "anthropic", "Gemini": "gemini", "模拟测试": "mock",
        }.get(display, display)

    @staticmethod
    def _protocol_display(value: str) -> str:
        return {
            "openai-compatible": "OpenAI 兼容接口", "openai": "OpenAI",
            "anthropic": "Anthropic", "gemini": "Gemini", "mock": "模拟测试",
        }.get(value, value)

    @staticmethod
    def _default_endpoint(provider: str, model: str = "") -> str:
        if provider == "anthropic":
            return "https://api.anthropic.com/v1/messages"
        if provider == "gemini":
            name = model or "gemini-2.0-flash"
            return f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent"
        if provider in {"openai", "openai-compatible"}:
            return "https://api.openai.com/v1/chat/completions"
        return ""

    def model_protocol_changed(self, _event: tk.Event | None = None) -> None:
        provider = self._protocol_value(self.model_protocol.get())
        self.model_endpoint.set(self._default_endpoint(provider, self.model_name.get()))
        defaults = {
            "openai": "OPENAI_API_KEY", "openai-compatible": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY", "mock": "",
        }
        self.model_api_env.set(defaults.get(provider, ""))

    def _model_settings_from_form(self) -> tuple[str, dict[str, Any]]:
        alias = self.model_alias.get().strip()
        if not alias or not re.fullmatch(r"[A-Za-z0-9_.-]+", alias):
            raise ValueError("配置名称只能包含字母、数字、点、下划线和连字符")
        provider = self._protocol_value(self.model_protocol.get())
        model = self.model_name.get().strip()
        if not model:
            raise ValueError("模型名称不能为空")
        values = deepcopy(self.model_profiles.get(alias, {}))
        values.update({
            "provider": provider,
            "model": model,
            "endpoint": self.model_endpoint.get().strip() or self._default_endpoint(provider, model),
            "api_key_env": self.model_api_env.get().strip(),
            "timeout_seconds": float(self.model_timeout.get()),
            "input_price_per_million": float(self.model_input_price.get()),
            "output_price_per_million": float(self.model_output_price.get()),
        })
        if provider == "mock":
            values.pop("endpoint", None)
            values.pop("api_key_env", None)
        elif not values["api_key_env"]:
            generated = re.sub(r"[^A-Za-z0-9]", "_", alias).upper()
            values["api_key_env"] = f"DELPHIOPT_{generated}_API_KEY"
            self.model_api_env.set(values["api_key_env"])
        if provider != "mock":
            if not str(values.get("endpoint", "")).startswith(("https://", "http://")):
                raise ValueError("接口地址必须以 http:// 或 https:// 开头")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(values.get("api_key_env", ""))):
                raise ValueError("密钥环境变量名格式无效")
        if values["timeout_seconds"] <= 0:
            raise ValueError("超时必须大于 0 秒")
        if values["input_price_per_million"] < 0 or values["output_price_per_million"] < 0:
            raise ValueError("模型价格不能为负数")
        return alias, values

    def _set_model_profiles(self, values: dict[str, Any]) -> None:
        models = values.get("models")
        if not isinstance(models, dict) or not models:
            return
        self.model_profiles = {
            str(alias): deepcopy(settings) for alias, settings in models.items() if isinstance(settings, dict)
        }
        configured = values.get("model_priority", [])
        priority = [str(alias) for alias in configured if alias in self.model_profiles] if isinstance(configured, list) else []
        self.model_priority = priority + [alias for alias in self.model_profiles if alias not in priority]
        self.model_priority_enabled.set(bool(values.get("model_priority_enabled", False)))
        self.refresh_model_table()

    def refresh_model_table(self) -> None:
        if not hasattr(self, "model_tree"):
            return
        self.model_tree.delete(*self.model_tree.get_children())
        for index, alias in enumerate(self.model_priority, 1):
            settings = self.model_profiles[alias]
            provider = self._protocol_display(str(settings.get("provider", "mock")))
            self.model_tree.insert(
                "", "end", iid=alias,
                values=(index, alias, provider, settings.get("model", "")),
            )

    def load_selected_model(self, _event: tk.Event | None = None) -> None:
        selection = self.model_tree.selection()
        if not selection:
            return
        alias = selection[0]
        settings = self.model_profiles[alias]
        provider = str(settings.get("provider", "mock"))
        self.model_alias.set(alias)
        self.model_protocol.set(self._protocol_display(provider))
        self.model_name.set(str(settings.get("model", "")))
        self.model_endpoint.set(str(settings.get("endpoint", self._default_endpoint(provider))))
        self.model_api_env.set(str(settings.get("api_key_env", "")))
        self.model_api_key.set("")
        self.model_timeout.set(float(settings.get("timeout_seconds", 120)))
        self.model_input_price.set(float(settings.get("input_price_per_million", 0)))
        self.model_output_price.set(float(settings.get("output_price_per_million", 0)))
        self.model_test_status.set("已载入配置，尚未测试连接")

    def clear_model_form(self) -> None:
        self.model_tree.selection_remove(self.model_tree.selection())
        self.model_alias.set("")
        self.model_protocol.set("OpenAI 兼容接口")
        self.model_name.set("")
        self.model_endpoint.set(self._default_endpoint("openai-compatible"))
        self.model_api_env.set("OPENAI_API_KEY")
        self.model_api_key.set("")
        self.model_timeout.set(120.0)
        self.model_input_price.set(0.0)
        self.model_output_price.set(0.0)
        self.model_test_status.set("尚未测试连接")

    def upsert_model(self) -> None:
        try:
            alias, settings = self._model_settings_from_form()
            self.backend.set_session_api_key(str(settings.get("api_key_env", "MOCK_KEY")), self.model_api_key.get())
        except (tk.TclError, TypeError, ValueError) as exc:
            messagebox.showerror("模型配置错误", str(exc))
            return
        is_new = alias not in self.model_profiles
        self.model_profiles[alias] = settings
        if is_new:
            self.model_priority.append(alias)
            self.model_priority_enabled.set(True)
        self.refresh_model_table()
        self.model_tree.selection_set(alias)
        self.model_tree.see(alias)
        self.raw_config = self.current_settings()
        self.form_to_yaml()
        messagebox.showinfo("DelphiOpt", "模型配置已更新。API 密钥仅保留在当前进程环境中。")

    def delete_model(self) -> None:
        selection = self.model_tree.selection()
        if not selection:
            messagebox.showinfo("DelphiOpt", "请先选择一个模型配置。")
            return
        alias = selection[0]
        if len(self.model_profiles) <= 1:
            messagebox.showerror("DelphiOpt", "至少需要保留一个模型配置。")
            return
        self.model_profiles.pop(alias, None)
        self.model_priority = [item for item in self.model_priority if item != alias]
        self.refresh_model_table()
        self.clear_model_form()
        self.raw_config = self.current_settings()
        self.form_to_yaml()

    def move_model(self, offset: int) -> None:
        selection = self.model_tree.selection()
        if not selection:
            messagebox.showinfo("DelphiOpt", "请先选择一个模型配置。")
            return
        alias = selection[0]
        index = self.model_priority.index(alias)
        destination = max(0, min(len(self.model_priority) - 1, index + offset))
        if destination == index:
            return
        self.model_priority[index], self.model_priority[destination] = (
            self.model_priority[destination], self.model_priority[index]
        )
        self.model_priority_enabled.set(True)
        self.refresh_model_table()
        self.model_tree.selection_set(alias)
        self.raw_config = self.current_settings()
        self.form_to_yaml()

    def test_model_connection(self) -> None:
        try:
            _alias, settings = self._model_settings_from_form()
        except (tk.TclError, TypeError, ValueError) as exc:
            messagebox.showerror("模型配置错误", str(exc))
            return
        if self.busy:
            messagebox.showinfo("DelphiOpt", "已有运行任务正在执行。")
            return
        self._set_busy(True)
        self.model_test_status.set("正在连接并请求模型…")

        def worker() -> None:
            code, output = self.backend.test_model_connection(settings, self.model_api_key.get())

            def finish() -> None:
                self.model_test_status.set(output)
                self._set_busy(False)
                if code == 0:
                    messagebox.showinfo("连接测试", output)
                else:
                    messagebox.showerror("连接测试", output)

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def current_settings(self) -> dict[str, Any]:
        base_path = Path(self.config_path.get()) if self.config_path.get() and Path(self.config_path.get()).is_file() else None
        values = self.backend.load_settings(base_path)
        if self.raw_config is not None:
            values = merge_config(values, self.raw_config)
        values["seed"] = self.seed.get()
        values["collaboration"]["mode"] = self._mode_value(self.mode.get())
        values["scheduler"].update({
            "strategy": self._scheduler_value(self.scheduler.get()),
            "base_tokens": self.base_tokens.get(),
            "tool_budget": self.scheduler_tool_budget.get(),
        })
        values["budget"].update({
            "max_cost_usd": self.budget.get(), "max_tokens": self.max_tokens.get(),
            "max_latency_seconds": self.max_latency.get(), "max_llm_calls": self.max_llm_calls.get(),
            "max_benchmark_runs": self.max_benchmark_runs.get(), "max_tool_calls": self.max_tool_calls.get(),
        })
        values["delphi"].update({
            "max_rounds": self.rounds.get(), "disagreement_threshold": self.disagreement_threshold.get(),
            "meaningful_speedup": self.meaningful_speedup.get(), "max_coefficient_of_variation": self.max_cv.get(),
            "marginal_gain_threshold": self.marginal_gain.get(), "min_utility_per_usd": self.min_utility.get(),
            "no_improvement_rounds": self.no_improvement_rounds.get(), "minority_bonus": self.minority_bonus.get(),
        })
        values["benchmark"].update({
            "warmups": self.warmups.get(), "repetitions": self.repetitions.get(),
            "timeout_seconds": self.benchmark_timeout.get(),
        })
        values["sandbox"].update({
            "type": self._sandbox_value(self.sandbox_type.get()), "network": self.sandbox_network.get(),
            "cpu_limit": self.cpu_limit.get(), "memory_mb": self.memory_mb.get(), "image": self.sandbox_image.get(),
        })
        values.setdefault("project", {}).update({
            "test_command": self.test_command.get(), "benchmark_command": self.benchmark_command.get(),
        })
        if self.lint_command.get().strip():
            values["project"]["lint_command"] = self.lint_command.get().strip()
        else:
            values["project"].pop("lint_command", None)
        if self.model_profiles:
            ordered_models = {
                alias: deepcopy(self.model_profiles[alias])
                for alias in self.model_priority if alias in self.model_profiles
            }
            values["models"] = ordered_models
            values["model_priority"] = list(ordered_models)
            values["model_priority_enabled"] = self.model_priority_enabled.get()
            for expert in values.get("experts", {}).values():
                if not isinstance(expert, dict):
                    continue
                pool = [alias for alias in expert.get("model_pool", []) if alias in ordered_models]
                expert["model_pool"] = pool or list(ordered_models)
        return values

    def _apply_settings(self, values: dict[str, Any]) -> None:
        def section(name: str) -> dict[str, Any]:
            value = values.get(name, {})
            return value if isinstance(value, dict) else {}

        budget, scheduler, delphi = section("budget"), section("scheduler"), section("delphi")
        benchmark, sandbox, project = section("benchmark"), section("sandbox"), section("project")
        mode_reverse = {"single": "单智能体", "best_of_n": "Best-of-N", "debate": "直接辩论", "delphi": "Delphi 协作"}
        scheduler_reverse = {"fixed": "固定调度", "difficulty": "难度路由", "difficulty_router": "难度路由", "adaptive_voi": "自适应 VOI"}
        self.seed.set(values.get("seed", 0))
        self.mode.set(mode_reverse.get(str(section("collaboration").get("mode", "delphi")), "Delphi 协作"))
        self.scheduler.set(scheduler_reverse.get(str(scheduler.get("strategy", "adaptive_voi")), "自适应 VOI"))
        assignments: tuple[tuple[tk.Variable, object], ...] = (
            (self.budget, budget.get("max_cost_usd", 1.0)), (self.max_tokens, budget.get("max_tokens", 150000)),
            (self.max_latency, budget.get("max_latency_seconds", 900)), (self.max_llm_calls, budget.get("max_llm_calls", 30)),
            (self.max_benchmark_runs, budget.get("max_benchmark_runs", 20)), (self.max_tool_calls, budget.get("max_tool_calls", 100)),
            (self.base_tokens, scheduler.get("base_tokens", 900)), (self.scheduler_tool_budget, scheduler.get("tool_budget", 2)),
            (self.rounds, delphi.get("max_rounds", 3)), (self.disagreement_threshold, delphi.get("disagreement_threshold", 0.08)),
            (self.meaningful_speedup, delphi.get("meaningful_speedup", 1.05)), (self.max_cv, delphi.get("max_coefficient_of_variation", 0.15)),
            (self.marginal_gain, delphi.get("marginal_gain_threshold", 0.02)), (self.min_utility, delphi.get("min_utility_per_usd", 0.1)),
            (self.no_improvement_rounds, delphi.get("no_improvement_rounds", 2)), (self.minority_bonus, delphi.get("minority_bonus", 0.12)),
            (self.warmups, benchmark.get("warmups", 2)), (self.repetitions, benchmark.get("repetitions", 5)),
            (self.benchmark_timeout, benchmark.get("timeout_seconds", 120)),
            (self.sandbox_type, {"local": "本地执行", "docker": "Docker 容器"}.get(str(sandbox.get("type", "local")), "本地执行")),
            (self.sandbox_network, sandbox.get("network", False)), (self.cpu_limit, sandbox.get("cpu_limit", 2)),
            (self.memory_mb, sandbox.get("memory_mb", 2048)), (self.sandbox_image, sandbox.get("image", "python:3.12-slim")),
            (self.test_command, project.get("test_command", "pytest -q")),
            (self.benchmark_command, project.get("benchmark_command", "python benchmark.py")),
            (self.lint_command, project.get("lint_command", "")),
        )
        for variable, value in assignments:
            variable.set(value)
        self._set_model_profiles(values)

    def apply_preset(self, name: str) -> None:
        presets = {
            "economy": (0.25, 50000, 10, 1, 1, 3),
            "balanced": (1.0, 150000, 30, 3, 2, 5),
            "deep": (5.0, 500000, 80, 5, 4, 10),
        }
        cost, tokens, calls, rounds, warmups, repetitions = presets[name]
        self.budget.set(cost)
        self.max_tokens.set(tokens)
        self.max_llm_calls.set(calls)
        self.rounds.set(rounds)
        self.warmups.set(warmups)
        self.repetitions.set(repetitions)
        self.form_to_yaml()
        messagebox.showinfo("DelphiOpt", "预设已应用，可继续微调任意参数。")

    def form_to_yaml(self) -> None:
        if not hasattr(self, "raw_yaml"):
            return
        self.raw_yaml.delete("1.0", "end")
        self.raw_yaml.insert("1.0", yaml.safe_dump(self.current_settings(), sort_keys=False, allow_unicode=True))

    def yaml_to_form(self) -> None:
        try:
            values = yaml.safe_load(self.raw_yaml.get("1.0", "end")) or {}
            if not isinstance(values, dict):
                raise TypeError("YAML 根节点必须是映射")
            valid, reason = self.backend.validate_settings(values)
            if not valid:
                raise ValueError(reason)
            self._apply_settings(values)
            self.raw_config = deepcopy(values)
            messagebox.showinfo("DelphiOpt", "YAML 已验证并应用到表单。")
        except (TypeError, ValueError, yaml.YAMLError) as exc:
            messagebox.showerror("配置错误", str(exc))

    def validate_current_settings(self) -> None:
        try:
            values = self.current_settings()
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror("配置错误", f"字段格式无效：{exc}")
            return
        valid, reason = self.backend.validate_settings(values)
        (messagebox.showinfo if valid else messagebox.showerror)("配置验证", reason)

    def save_settings_file(self) -> None:
        path = filedialog.asksaveasfilename(
            title="保存 DelphiOpt 配置", defaultextension=".yaml",
            filetypes=(("YAML 配置", "*.yaml *.yml"), ("所有文件", "*.*")),
        )
        if not path:
            return
        try:
            values = self.current_settings()
            self.backend.save_settings(Path(path), values)
            self.config_path.set(path)
            self.raw_config = deepcopy(values)
            self.form_to_yaml()
            messagebox.showinfo("DelphiOpt", f"配置已保存：\n{path}")
        except (OSError, TypeError, ValueError, tk.TclError) as exc:
            messagebox.showerror("保存失败", str(exc))

    def load_settings_file(self) -> None:
        path = filedialog.askopenfilename(
            title="载入 DelphiOpt 配置", filetypes=(("YAML 配置", "*.yaml *.yml"), ("所有文件", "*.*")),
        )
        if not path:
            return
        try:
            values = self.backend.load_settings(Path(path))
            self._apply_settings(values)
            self.raw_config = deepcopy(values)
            self.config_path.set(path)
            self.form_to_yaml()
            messagebox.showinfo("DelphiOpt", "配置已载入。")
        except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            messagebox.showerror("载入失败", str(exc))

    def refresh_diagnostics(self) -> None:
        if not hasattr(self, "provider_rows"):
            return
        for child in self.provider_rows.winfo_children():
            child.destroy()
        data = self.backend.diagnostics()
        self._label(self.provider_rows, f"Python {data['python']}  ·  应用目录 {data['app_home']}", color=TEXT, bold=True).pack(anchor="w", pady=(0, 10))
        providers = data["providers"]
        if isinstance(providers, dict):
            for name, connected in providers.items():
                row = tk.Frame(self.provider_rows, bg=PANEL)
                row.pack(fill="x", pady=4)
                self._label(row, "●", color=GREEN if connected else MUTED).pack(side="left")
                self._label(row, str(name), color=TEXT, bold=True).pack(side="left", padx=10)
                self._label(row, "已就绪" if connected else "未配置环境变量", color=GREEN if connected else MUTED, size=8, bold=True).pack(side="right")

    def show_page(self, name: str) -> None:
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.page_title.set(name)
        for key, button in self.nav.items():
            button.configure(bg=PANEL_2 if key == name else SIDEBAR, fg=TEXT if key == name else MUTED)
        if name == "运行与报告":
            self.refresh_runs()

    def choose_project(self) -> None:
        value = filedialog.askdirectory(initialdir=self.project.get(), title="选择 DelphiOpt 项目")
        if value:
            self.project.set(value)
            self.refresh_runs()

    def choose_config(self) -> None:
        value = filedialog.askopenfilename(
            title="选择配置文件", filetypes=(("YAML 配置", "*.yaml *.yml"), ("所有文件", "*.*"))
        )
        if value:
            self.config_path.set(value)
            try:
                settings = self.backend.load_settings(Path(value))
                self.raw_config = deepcopy(settings)
                self._apply_settings(settings)
                self.form_to_yaml()
            except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
                messagebox.showerror("配置错误", str(exc))

    def _load_preferences(self) -> None:
        path = self.backend.app_home / "ui_preferences.json"
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        project_value = str(values.get("project", "")).strip()
        config_value = str(values.get("config", "")).strip()
        project = Path(project_value) if project_value else None
        config = Path(config_value) if config_value else None
        if project and project.is_dir():
            self.project.set(str(project))
        if config and config.is_file():
            self.config_path.set(str(config))
        self.auto_open_report.set(bool(values.get("auto_open_report", True)))

    def close_app(self) -> None:
        values = {
            "project": self.project.get(),
            "config": self.config_path.get(),
            "auto_open_report": self.auto_open_report.get(),
        }
        try:
            (self.backend.app_home / "ui_preferences.json").write_text(
                json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
        self.destroy()

    def _write(self, console: tk.Text, message: str, clear: bool = False) -> None:
        console.configure(state="normal")
        if clear:
            console.delete("1.0", "end")
        console.insert("end", message.rstrip() + "\n")
        console.see("end")
        console.configure(state="disabled")

    def clear_console(self, console: tk.Text) -> None:
        console.configure(state="normal")
        console.delete("1.0", "end")
        console.configure(state="disabled")

    def copy_console(self, console: tk.Text) -> None:
        self.clipboard_clear()
        self.clipboard_append(console.get("1.0", "end").strip())
        self.update()

    def _set_busy(self, value: bool) -> None:
        self.busy = value
        self.status_text.set("运行中" if value else "就绪")
        self.status_dot.configure(fg=AMBER if value else GREEN)

    def _run(self, console: tk.Text, label: str, job: Callable[[], tuple[int, str]], done: Callable[[int, str], None] | None = None) -> None:
        if self.busy:
            messagebox.showinfo("DelphiOpt", "已有运行任务正在执行。")
            return
        self._set_busy(True)
        self._write(console, f"[{time.strftime('%H:%M:%S')}] {label}", clear=True)

        def worker() -> None:
            code, output = job()

            def finish() -> None:
                self._write(console, output or "（无输出）")
                self._write(console, f"\n退出状态：{code}")
                self._set_busy(False)
                if done:
                    done(code, output)

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _project_path(self) -> Path | None:
        path = Path(self.project.get()).expanduser()
        if not path.exists():
            messagebox.showerror("DelphiOpt", f"项目目录不存在：\n{path}")
            return None
        return path.resolve()

    def launch_optimize(self) -> None:
        project = self._project_path()
        if project is None:
            return
        base = Path(self.config_path.get()) if self.config_path.get() and Path(self.config_path.get()).is_file() else None
        try:
            settings = self.current_settings()
            override = self.backend.make_override(
                self._scheduler_value(self.scheduler.get()), self.rounds.get(), base, settings
            )
        except (TypeError, ValueError, tk.TclError) as exc:
            messagebox.showerror("配置错误", str(exc))
            return
        args = [
            "optimize", str(project), "--config", str(override), "--budget-usd", str(self.budget.get()),
            "--max-rounds", str(self.rounds.get()), "--mode", self._mode_value(self.mode.get()),
        ]
        self._run(self.optimize_console, "正在启动优化运行时…", lambda: self.backend.run_cli(args), self._optimization_done)

    def preflight_project(self) -> None:
        project = self._project_path()
        if project is None:
            return
        try:
            settings = self.current_settings()
        except (TypeError, ValueError, tk.TclError) as exc:
            messagebox.showerror("配置错误", str(exc))
            return
        self._run(
            self.optimize_console,
            "正在执行项目预检…",
            lambda: self.backend.preflight(project, settings),
        )

    def _optimization_done(self, code: int, output: str) -> None:
        try:
            data = json.loads(output[output.index("{"):])
        except (ValueError, json.JSONDecodeError):
            data = {}
        if data:
            status = {"accepted": "已接受", "rejected": "已拒绝", "failed": "失败"}.get(
                str(data.get("status")), str(data.get("status", "已完成"))
            )
            self.metrics["status"].configure(text=status)
            self.metrics["speedup"].configure(text=f"{float(data.get('speedup', 1.0)):.2f}×")
            self.metrics["correctness"].configure(text="通过" if data.get("correctness") else "失败")
            self.metrics["calls"].configure(text=str(data.get("llm_calls", "—")))
        self.refresh_runs()
        if code == 0:
            self.status_text.set("已完成")

    def launch_benchmark(self) -> None:
        project = self._project_path()
        if project is None:
            return
        base = Path(self.config_path.get()) if self.config_path.get() and Path(self.config_path.get()).is_file() else None
        try:
            override = self.backend.make_override(
                self._scheduler_value(self.scheduler.get()), self.rounds.get(), base, self.current_settings()
            )
        except (TypeError, ValueError, tk.TclError) as exc:
            messagebox.showerror("配置错误", str(exc))
            return
        args = ["benchmark", str(project), "--config", str(override)]
        self._run(self.experiment_console, "正在运行正确性门禁与基准测试…", lambda: self.backend.run_cli(args))

    def launch_ablation(self) -> None:
        project = self._project_path()
        if project is None:
            return
        self._run(
            self.experiment_console,
            "正在启动完整消融实验…",
            lambda: self.backend.execute_ablation(
                project, lambda msg: self.after(0, lambda: self._write(self.experiment_console, msg))
            ),
        )

    def open_ablation_report(self) -> None:
        path = self.backend.app_home / "experiments" / "ablation_report.html"
        if path.exists():
            self.backend.open_path(path)
        else:
            messagebox.showinfo("DelphiOpt", "请先运行消融实验。")

    def refresh_runs(self) -> None:
        if not hasattr(self, "run_tree"):
            return
        self.run_tree.delete(*self.run_tree.get_children())
        path = Path(self.project.get()).expanduser()
        if not path.exists():
            return
        for row in self.backend.list_runs(path):
            run_id = str(row["_run_id"])
            status = {"accepted": "已接受", "rejected": "已拒绝", "failed": "失败"}.get(
                str(row.get("status")), str(row.get("status", "—"))
            )
            self.run_tree.insert(
                "", "end", iid=run_id,
                values=(
                    run_id, status, f"{float(row.get('speedup', 1.0)):.3f}×",
                    "通过" if row.get("correctness") else "失败",
                    f"${float(row.get('cost_usd', 0.0)):.4f}",
                    row.get("total_tokens", 0), row.get("rounds", 0),
                ),
            )

    def _selected_run(self) -> tuple[str, Path] | None:
        selection = self.run_tree.selection()
        if not selection:
            messagebox.showinfo("DelphiOpt", "请先选择一条运行记录。")
            return None
        return selection[0], Path(self.project.get()) / ".delphiopt" / "runs"

    def open_runs_folder(self) -> None:
        root = Path(self.project.get()) / ".delphiopt" / "runs"
        root.mkdir(parents=True, exist_ok=True)
        self.backend.open_path(root)

    def export_selected_summary(self) -> None:
        selected = self._selected_run()
        if not selected:
            return
        run_id, root = selected
        source = root / f"{run_id}.summary.json"
        if not source.exists():
            messagebox.showinfo("DelphiOpt", "该运行记录没有可导出的摘要。")
            return
        destination = filedialog.asksaveasfilename(
            title="导出运行摘要", initialfile=f"{run_id}.summary.json",
            defaultextension=".json", filetypes=(("JSON 摘要", "*.json"), ("所有文件", "*.*")),
        )
        if not destination:
            return
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
            Path(destination).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            messagebox.showinfo("导出完成", f"运行摘要已导出：\n{destination}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("导出失败", str(exc))

    def inspect_selected(self) -> None:
        selected = self._selected_run()
        if selected:
            run_id, root = selected
            self._run(self.run_console, f"正在查看运行追踪 {run_id}…", lambda: self.backend.run_cli(["inspect", run_id, "--runs-root", str(root)]))

    def report_selected(self) -> None:
        selected = self._selected_run()
        if not selected:
            return
        run_id, root = selected

        def done(code: int, output: str) -> None:
            path = Path(output.splitlines()[-1]) if output else Path()
            if code == 0 and path.exists() and self.auto_open_report.get():
                self.backend.open_path(path)

        self._run(self.run_console, f"正在为 {run_id} 生成报告…", lambda: self.backend.run_cli(["report", run_id, "--runs-root", str(root)]), done)

    def reproduce_selected(self) -> None:
        selected = self._selected_run()
        if selected:
            run_id, root = selected
            self._run(self.run_console, f"正在复现 {run_id}…", lambda: self.backend.run_cli(["reproduce", run_id, "--runs-root", str(root)]), lambda _c, _o: self.refresh_runs())

    def load_models(self) -> None:
        args = ["models"]
        if self.config_path.get() and Path(self.config_path.get()).is_file():
            args.extend(("--config", self.config_path.get()))
        self._run(self.catalog_console, "正在解析模型目录…", lambda: self.backend.run_cli(args))

    def load_experts(self) -> None:
        args = ["experts"]
        if self.config_path.get() and Path(self.config_path.get()).is_file():
            args.extend(("--config", self.config_path.get()))
        self._run(self.catalog_console, "正在解析专家目录…", lambda: self.backend.run_cli(args))


def self_test(output: Path) -> int:
    backend = FrontendBackend()
    demo = backend.ensure_demo()
    model_code, models = backend.run_cli(["models"])
    expert_code, experts = backend.run_cli(["experts"])
    result = {
        "status": "passed" if model_code == expert_code == 0 and demo.exists() else "failed",
        "demo": str(demo),
        "models": len(models.splitlines()),
        "experts": len(experts.splitlines()),
        "commands": {"models": model_code, "experts": expert_code},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["status"] == "passed" else 1


def ui_smoke_test(output: Path) -> int:
    app = DelphiOptDesktop()
    app.update_idletasks()
    settings = app.current_settings()
    app.show_page("高级设置")
    app.settings_notebook.select(4)
    app.update_idletasks()
    mock_model_code, _mock_model_output = app.backend.test_model_connection(
        {"provider": "mock", "model": "mock-smoke"}
    )
    result = {
        "status": "通过",
        "title": app.title(),
        "geometry": app.geometry(),
        "pages": list(app.pages),
        "controls": {
            "协作模式": ["单智能体", "Best-of-N", "直接辩论", "Delphi 协作"],
            "调度策略": ["固定调度", "难度路由", "自适应 VOI"],
            "高级设置": [
                "预算与调度", "基准测试", "Delphi 策略", "沙箱与项目",
                "模型接入", "系统诊断", "高级 YAML",
            ],
        },
        "功能检查": {
            "预算字段数": len(settings["budget"]),
            "Delphi字段数": len(settings["delphi"]),
            "基准字段数": len(settings["benchmark"]),
            "沙箱字段数": len(settings["sandbox"]),
            "高级YAML可用": bool(app.raw_yaml.get("1.0", "end").strip()),
            "项目预检可用": callable(app.preflight_project),
            "运行摘要导出可用": callable(app.export_selected_summary),
            "模型连接测试可用": callable(app.test_model_connection),
            "模型优先级可用": callable(app.move_model),
            "模型配置数": len(app.model_profiles),
            "模型优先级表宽度": app.model_tree.winfo_width(),
            "模型列表字段完整": app.model_tree.winfo_width() >= 390,
            "模拟连接测试通过": mock_model_code == 0,
            "优化任务布局列数": app.optimize_layout_columns,
            "高分屏缩放": float(app.tk.call("tk", "scaling")),
        },
    }
    result["status"] = "通过" if mock_model_code == 0 and result["功能检查"]["模型列表字段完整"] else "失败"
    app.destroy()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["status"] == "通过" else 1


def main() -> int:
    if "--self-test-output" in sys.argv:
        index = sys.argv.index("--self-test-output")
        return self_test(Path(sys.argv[index + 1]).resolve())
    if "--ui-smoke-output" in sys.argv:
        index = sys.argv.index("--ui-smoke-output")
        return ui_smoke_test(Path(sys.argv[index + 1]).resolve())
    app = DelphiOptDesktop()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
