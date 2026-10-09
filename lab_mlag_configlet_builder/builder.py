"""Generate device-specific EOS MLAG configlets for lab switches."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from .models import DeviceMlagParams, MlagLabInputs, load_inputs
from .safety import assert_safe_eos_config, ensure_no_management_interfaces


def _port_channel_number(port_channel: str) -> str:
    """Extract the numeric suffix from Port-ChannelN / PoN / port-channelN."""
    name = port_channel.strip()
    lower = name.lower().replace("-", "").replace(" ", "")
    for prefix in ("portchannel", "po"):
        if lower.startswith(prefix):
            digits = lower[len(prefix) :]
            if digits.isdigit():
                return digits
    digits = "".join(ch for ch in name if ch.isdigit())
    if not digits:
        raise ValueError(f"cannot determine Port-Channel number from {port_channel!r}")
    return digits


def _normalize_port_channel(port_channel: str) -> str:
    return f"Port-Channel{_port_channel_number(port_channel)}"


def _normalize_vlan_intf(vlan_id: int) -> str:
    return f"Vlan{vlan_id}"


class MlagConfigletBuilder:
    """Build additive EOS MLAG configlets from validated lab inputs."""

    def __init__(self, inputs: MlagLabInputs) -> None:
        self.inputs = inputs
        self._validate_interfaces()

    def _validate_interfaces(self) -> None:
        names: List[str] = []
        names.extend(self.inputs.peer_link.members)
        names.append(self.inputs.peer_link.port_channel)
        names.extend(self.inputs.downstream.members)
        names.append(self.inputs.downstream.port_channel)
        ensure_no_management_interfaces(names)

    def device_names(self) -> List[str]:
        return sorted(self.inputs.devices)

    def build(self, hostname: str) -> str:
        """Return a single-device EOS configlet string."""
        device = self.inputs.require_device(hostname)
        lines = self._render_device(device)
        config = "\n".join(lines).rstrip() + "\n"
        assert_safe_eos_config(config)
        return config

    def build_all(self) -> Dict[str, str]:
        """Return hostname → configlet for every configured device."""
        return {name: self.build(name) for name in self.device_names()}

    def _render_device(self, device: DeviceMlagParams) -> List[str]:
        inputs = self.inputs
        peer_pc = _normalize_port_channel(inputs.peer_link.port_channel)
        peer_pc_num = _port_channel_number(peer_pc)
        down_pc = _normalize_port_channel(inputs.downstream.port_channel)
        down_pc_num = _port_channel_number(down_pc)
        vlan_intf = _normalize_vlan_intf(inputs.peer_vlan)
        trunk_group = inputs.peer_link.trunk_group

        # Downstream MLAG ID: prefer per-device override, else shared downstream.mlag_id.
        mlag_id = device.mlag_id if device.mlag_id is not None else inputs.downstream.mlag_id

        lines: List[str] = [
            f"! MLAG configlet for {device.hostname}",
            f"! domain-id: {inputs.domain_id}",
            f"! Additive only — does not reset interfaces or alter management",
            "!",
            f"vlan {inputs.peer_vlan}",
            f"   name {inputs.peer_vlan_name}",
            f"   trunk group {trunk_group}",
            "!",
            f"interface {peer_pc}",
            f"   description {inputs.peer_link_description}",
            "   switchport mode trunk",
            f"   switchport trunk group {trunk_group}",
            "   no shutdown",
            "!",
        ]

        for member in inputs.peer_link.members:
            lines.extend(
                [
                    f"interface {member}",
                    f"   description {inputs.peer_link_description}",
                    f"   channel-group {peer_pc_num} mode active",
                    "   no shutdown",
                    "!",
                ]
            )

        lines.extend(
            [
                f"interface {vlan_intf}",
                f"   description {inputs.peer_vlan_name}",
                f"   ip address {device.peer_svi_ip}",
                "   no shutdown",
                "!",
                "mlag configuration",
                f"   domain-id {inputs.domain_id}",
                f"   local-interface {vlan_intf}",
                f"   peer-address {device.peer_address}",
                f"   peer-link {peer_pc}",
                "!",
                f"interface {down_pc}",
                f"   description {inputs.downstream.description}",
            ]
        )

        if inputs.downstream.switchport_mode == "trunk":
            lines.append("   switchport mode trunk")
            if inputs.downstream.trunk_allowed_vlans:
                lines.append(
                    f"   switchport trunk allowed vlan {inputs.downstream.trunk_allowed_vlans}"
                )
        else:
            lines.append("   switchport mode access")

        lines.extend(
            [
                f"   mlag {mlag_id}",
                "   no shutdown",
                "!",
            ]
        )

        for member in inputs.downstream.members:
            lines.extend(
                [
                    f"interface {member}",
                    f"   description {inputs.downstream.description}",
                    f"   channel-group {down_pc_num} mode active",
                    "   no shutdown",
                    "!",
                ]
            )

        return lines


def build_configlets_from_file(
    path: str | Path,
    devices: Optional[Iterable[str]] = None,
) -> Mapping[str, str]:
    """Load YAML inputs and build one or more device configlets."""
    inputs = load_inputs(path)
    builder = MlagConfigletBuilder(inputs)
    if devices is None:
        return builder.build_all()
    return {name: builder.build(name) for name in devices}
