from __future__ import annotations

from dataclasses import dataclass, field
import time
from pathlib import Path
from typing import Any

from orbit.runtime.project_env import get_obsidian_vault_root

from orbit.runtime.mcp.bootstrap import (
    bootstrap_local_filesystem_mcp_server,  # kept as fallback reference
    bootstrap_local_git_mcp_server,
    bootstrap_local_obsidian_mcp_server,
)
from orbit.runtime.mcp.daemon_lifecycle import ensure_filesystem_daemon_bootstrap
from orbit.runtime.mcp.obsidian_daemon_lifecycle import ensure_obsidian_daemon_bootstrap
from orbit.runtime.mcp.bash_bootstrap import bootstrap_local_bash_mcp_server
from orbit.runtime.mcp.browser_bootstrap import bootstrap_local_browser_mcp_server
from orbit.runtime.mcp.mypy_bootstrap import bootstrap_local_mypy_mcp_server
from orbit.runtime.mcp.process_bootstrap import bootstrap_local_process_mcp_server
from orbit.runtime.mcp.pytest_bootstrap import bootstrap_local_pytest_mcp_server
from orbit.runtime.mcp.registry_loader import register_mcp_server_tools
from orbit.runtime.mcp.ruff_bootstrap import bootstrap_local_ruff_mcp_server
from orbit.runtime.extensions.capability_registry import RegistryBackedCapabilityToolRegistry
from orbit.tools.registry import ToolRegistry


@dataclass
class RuntimeCapabilityProfile:
    filesystem: bool = False
    git: bool = False
    bash: bool = False
    process: bool = False
    pytest: bool = False
    ruff: bool = False
    mypy: bool = False
    browser: bool = False
    obsidian: bool = False
    memory: bool = False


@dataclass
class RuntimeCapabilityBundle:
    tool_registry: ToolRegistry
    capability_tool_registry: RegistryBackedCapabilityToolRegistry | None = None
    embedding_service: Any | None = None
    memory_service: Any | None = None
    enabled_capabilities: set[str] = field(default_factory=set)
    activation_metrics: dict[str, float] = field(default_factory=dict)
    warmup_metrics: dict[str, float] = field(default_factory=dict)


class RuntimeCapabilityComposer:
    def __init__(self, *, workspace_root: str, backend=None):
        self.workspace_root = str(workspace_root)
        self.backend = backend

    def _record(self, bucket: dict[str, float], key: str, started_at: float) -> None:
        bucket[key] = round((time.perf_counter() - started_at) * 1000, 2)

    def _filesystem_bootstrap_with_fallback(self, bundle: RuntimeCapabilityBundle):
        """Try daemon bootstrap; fall back to stdio if the daemon fails to start."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            bootstrap = ensure_filesystem_daemon_bootstrap(workspace_root=self.workspace_root)
            bundle.activation_metrics['filesystem_transport_mode'] = 'daemon'
            return bootstrap
        except Exception as exc:
            logger.warning("filesystem daemon bootstrap failed (%s), falling back to stdio", exc)
            bundle.activation_metrics['filesystem_transport_mode'] = 'stdio_fallback'
            return bootstrap_local_filesystem_mcp_server(workspace_root=self.workspace_root)

    def _obsidian_bootstrap_with_fallback(self, vault_root: str, bundle: RuntimeCapabilityBundle):
        """Try daemon bootstrap; fall back to stdio if the daemon fails to start."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            bootstrap = ensure_obsidian_daemon_bootstrap(
                workspace_root=self.workspace_root,
                vault_root=vault_root,
            )
            bundle.activation_metrics['obsidian_transport_mode'] = 'daemon'
            return bootstrap
        except Exception as exc:
            logger.warning("obsidian daemon bootstrap failed (%s), falling back to stdio", exc)
            bundle.activation_metrics['obsidian_transport_mode'] = 'stdio_fallback'
            return bootstrap_local_obsidian_mcp_server(vault_root=vault_root)

    def _activate_mcp_family(self, *, bundle: RuntimeCapabilityBundle, capability: str, bootstrap_factory) -> None:
        t = time.perf_counter()
        bootstrap = bootstrap_factory()
        register_mcp_server_tools(registry=bundle.tool_registry, bootstrap=bootstrap)
        self._record(bundle.activation_metrics, f'{capability}_activation_ms', t)
        bundle.enabled_capabilities.add(capability)

    def _maybe_enable_memory(self, *, bundle: RuntimeCapabilityBundle) -> None:
        if bundle.memory_service is not None:
            return
        t = time.perf_counter()
        from orbit.memory import EmbeddingService, MemoryService
        self._record(bundle.activation_metrics, 'memory_import_deferred_ms', t)
        t = time.perf_counter()
        bundle.embedding_service = EmbeddingService()
        self._record(bundle.activation_metrics, 'embedding_service_init_ms', t)
        t = time.perf_counter()
        bundle.memory_service = MemoryService(store=getattr(self.backend, 'store', None), embedding_service=bundle.embedding_service)
        self._record(bundle.activation_metrics, 'memory_service_init_ms', t)
        if hasattr(self.backend, 'memory_service'):
            t = time.perf_counter()
            self.backend.memory_service = bundle.memory_service
            self._record(bundle.activation_metrics, 'backend_memory_service_bind_ms', t)
        bundle.enabled_capabilities.add('memory')

    def activate(self, profile: RuntimeCapabilityProfile) -> RuntimeCapabilityBundle:
        t0 = time.perf_counter()
        bundle = RuntimeCapabilityBundle(tool_registry=ToolRegistry(Path(self.workspace_root)))
        bundle.capability_tool_registry = RegistryBackedCapabilityToolRegistry(tool_registry=bundle.tool_registry)
        bundle.activation_metrics['tool_registry_init_ms'] = round((time.perf_counter() - t0) * 1000, 2)

        if profile.filesystem:
            # Filesystem tools via the daemon socket transport.
            # The daemon is auto-ensured (spawned if absent, reused if running).
            # Falls back to stdio bootstrap if the daemon fails to start.
            self._activate_mcp_family(
                bundle=bundle,
                capability='filesystem',
                bootstrap_factory=lambda: self._filesystem_bootstrap_with_fallback(bundle),
            )
        if profile.git:
            self._activate_mcp_family(
                bundle=bundle,
                capability='git',
                bootstrap_factory=lambda: bootstrap_local_git_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.bash:
            self._activate_mcp_family(
                bundle=bundle,
                capability='bash',
                bootstrap_factory=lambda: bootstrap_local_bash_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.process:
            self._activate_mcp_family(
                bundle=bundle,
                capability='process',
                bootstrap_factory=lambda: bootstrap_local_process_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.pytest:
            self._activate_mcp_family(
                bundle=bundle,
                capability='pytest',
                bootstrap_factory=lambda: bootstrap_local_pytest_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.ruff:
            self._activate_mcp_family(
                bundle=bundle,
                capability='ruff',
                bootstrap_factory=lambda: bootstrap_local_ruff_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.mypy:
            self._activate_mcp_family(
                bundle=bundle,
                capability='mypy',
                bootstrap_factory=lambda: bootstrap_local_mypy_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.browser:
            self._activate_mcp_family(
                bundle=bundle,
                capability='browser',
                bootstrap_factory=lambda: bootstrap_local_browser_mcp_server(workspace_root=self.workspace_root),
            )
        if profile.obsidian:
            vault_root = get_obsidian_vault_root()
            if vault_root:
                self._activate_mcp_family(
                    bundle=bundle,
                    capability='obsidian',
                    bootstrap_factory=lambda: self._obsidian_bootstrap_with_fallback(vault_root=vault_root, bundle=bundle),
                )
        if profile.memory:
            self._maybe_enable_memory(bundle=bundle)
        else:
            bundle.activation_metrics['memory_enabled'] = False

        if hasattr(self.backend, 'tool_registry'):
            t = time.perf_counter()
            self.backend.tool_registry = bundle.tool_registry
            self._record(bundle.activation_metrics, 'backend_tool_registry_bind_ms', t)
        if hasattr(self.backend, 'capability_tool_registry'):
            t = time.perf_counter()
            self.backend.capability_tool_registry = bundle.capability_tool_registry
            self._record(bundle.activation_metrics, 'backend_capability_tool_registry_bind_ms', t)
        bundle.activation_metrics['total_ms'] = round(sum(v for v in bundle.activation_metrics.values() if isinstance(v, (int, float))), 2)
        return bundle

    def ensure_capability(self, bundle: RuntimeCapabilityBundle, capability: str) -> bool:
        """Incrementally activate a single capability family into an existing bundle.

        Returns True if the capability was newly activated, False if already enabled.
        Raises on activation failure (caller decides whether to swallow).
        """
        if capability in bundle.enabled_capabilities:
            return False

        factory = self._bootstrap_factory_for(capability, bundle=bundle)
        if factory is None:
            return False

        self._activate_mcp_family(bundle=bundle, capability=capability, bootstrap_factory=factory)

        # Re-bind backend registries so newly registered tools are visible immediately
        if hasattr(self.backend, 'tool_registry'):
            self.backend.tool_registry = bundle.tool_registry
        if hasattr(self.backend, 'capability_tool_registry'):
            self.backend.capability_tool_registry = bundle.capability_tool_registry

        return True

    def _bootstrap_factory_for(self, capability: str, *, bundle: RuntimeCapabilityBundle):
        """Return the bootstrap factory callable for a capability name, or None."""
        factories = {
            'filesystem': lambda: self._filesystem_bootstrap_with_fallback(bundle),
            'git': lambda: bootstrap_local_git_mcp_server(workspace_root=self.workspace_root),
            'bash': lambda: bootstrap_local_bash_mcp_server(workspace_root=self.workspace_root),
            'process': lambda: bootstrap_local_process_mcp_server(workspace_root=self.workspace_root),
            'pytest': lambda: bootstrap_local_pytest_mcp_server(workspace_root=self.workspace_root),
            'ruff': lambda: bootstrap_local_ruff_mcp_server(workspace_root=self.workspace_root),
            'mypy': lambda: bootstrap_local_mypy_mcp_server(workspace_root=self.workspace_root),
            'browser': lambda: bootstrap_local_browser_mcp_server(workspace_root=self.workspace_root),
        }
        if capability == 'obsidian':
            vault_root = get_obsidian_vault_root()
            if vault_root:
                return lambda: self._obsidian_bootstrap_with_fallback(vault_root=vault_root, bundle=bundle)
            return None
        return factories.get(capability)

    def warmup(self, bundle: RuntimeCapabilityBundle, *, capabilities: list[str] | None = None) -> dict[str, float]:
        t0 = time.perf_counter()
        selected = set(capabilities or bundle.enabled_capabilities)
        metrics: dict[str, float] = {}
        if 'memory' in selected and bundle.embedding_service is not None:
            step = time.perf_counter()
            try:
                bundle.embedding_service.embed_text('orbit_warmup_prefetch')
            except Exception:
                pass
            metrics['warmup_memory_ms'] = round((time.perf_counter() - step) * 1000, 2)
        for family in sorted(selected):
            metrics.setdefault(f'warmup_{family}_ms', 0.0)
        metrics['warmup_total_ms'] = round((time.perf_counter() - t0) * 1000, 2)
        bundle.warmup_metrics.update(metrics)
        return metrics
