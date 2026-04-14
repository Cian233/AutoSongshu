from __future__ import annotations

import logging
from typing import Any, Callable

from ..config import AppConfig

logger = logging.getLogger(__name__)


class MCPManager:
    """
    MCP (Model Context Protocol) 管理器占位符结构。
    负责加载和管理 MCP 服务器连接。
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.servers: dict[str, Any] = {}
        self._resource_subscriptions: dict[str, dict[str, Any]] = {}

    async def load_servers(self) -> None:
        """
        根据配置加载 MCP 服务器。
        目前仅作为占位符，后续将实现实际的加载逻辑。
        """
        if not self.config.mcp_servers:
            logger.info("未配置 MCP 服务器。")
            return

        for name, server_config in self.config.mcp_servers.items():
            logger.info(f"正在加载 MCP 服务器: {name}")
            # TODO: 实现 MCP 服务器加载逻辑
            # self.servers[name] = await self._connect_to_server(server_config)
            pass

    async def close(self) -> None:
        """
        关闭所有 MCP 服务器连接。
        """
        # TODO: 实现关闭逻辑
        pass

    # ── SubTask 7.1: MCP Tool Dynamic Discovery and Registration ──

    async def discover_tools(self, server_name: str) -> list[dict]:
        """
        从指定的 MCP 服务器发现可用工具。

        调用 tools/list 方法获取服务器提供的工具列表及其元数据。

        Args:
            server_name: MCP 服务器名称。

        Returns:
            可用工具列表，每个工具包含 name、description、inputSchema 等元数据。

        Raises:
            ValueError: 如果服务器未加载或不支持 tools 能力。
        """
        if server_name not in self.servers:
            raise ValueError(f"MCP 服务器 '{server_name}' 未加载。")

        server = self.servers[server_name]
        if not hasattr(server, "list_tools"):
            raise ValueError(f"MCP 服务器 '{server_name}' 不支持 tools 能力。")

        tools_result = await server.list_tools()
        tools_list = []

        for tool in tools_result.tools:
            tool_info = {
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema,
            }
            tools_list.append(tool_info)

        logger.info(
            f"从 MCP 服务器 '{server_name}' 发现了 {len(tools_list)} 个工具。"
        )
        return tools_list

    async def register_mcp_tools(self, tools: list[dict], server_name: str) -> list[str]:
        """
        将发现的 MCP 工具注册到 ToolRegistry。

        Args:
            tools: 工具元数据列表，每个工具包含 name、description、inputSchema。
            server_name: MCP 服务器名称，用于绑定工具调用。

        Returns:
            已注册的工具名称列表。
        """
        from ..tool_impls.registry import registry
        from ..permissions import ToolRiskLevel

        registered_names = []

        for tool in tools:
            tool_name = tool["name"]
            description = tool.get("description", "")
            input_schema = tool.get("inputSchema", {})

            def _create_mcp_tool_func(name: str, srv_name: str, schema: dict):
                async def mcp_tool_call(**kwargs) -> Any:
                    server = self.servers[srv_name]
                    if hasattr(server, "call_tool"):
                        result = await server.call_tool(name, kwargs)
                        return result
                    raise NotImplementedError(
                        f"MCP 服务器 '{srv_name}' 不支持 call_tool。"
                    )
                mcp_tool_call.__name__ = name
                mcp_tool_call.__doc__ = schema.get("description", "")
                return mcp_tool_call

            tool_func = _create_mcp_tool_func(tool_name, server_name, input_schema)

            decorator = registry.register(
                group_name="mcp",
                description=description,
                risk_level=ToolRiskLevel.MEDIUM,
            )
            decorator(tool_func)

            logger.info(f"注册 MCP 工具: {tool_name}")
            registered_names.append(tool_name)

        logger.info(f"成功注册 {len(registered_names)} 个 MCP 工具。")
        return registered_names

    async def handle_tools_list_changed(self, server_name: str) -> list[str]:
        """
        处理 tools/listChanged 通知。

        当 MCP 服务器发送 tools/listChanged 通知时，重新发现并注册工具。

        Args:
            server_name: 发送通知的 MCP 服务器名称。

        Returns:
            重新注册的工具名称列表。
        """
        logger.info(
            f"收到来自 MCP 服务器 '{server_name}' 的 tools/listChanged 通知。"
        )

        tools = await self.discover_tools(server_name)
        registered = await self.register_mcp_tools(tools, server_name)

        logger.info(
            f"已重新注册 {len(registered)} 个工具来自服务器 '{server_name}'。"
        )
        return registered

    # ── SubTask 7.2: MCP Resource Subscription Support ──

    async def subscribe_to_resource(
        self,
        server_name: str,
        resource_uri: str,
        callback: Callable,
    ) -> str:
        """
        订阅 MCP 服务器的资源变更。

        当资源发生变化时，将调用提供的回调函数。

        Args:
            server_name: MCP 服务器名称。
            resource_uri: 要订阅的资源 URI。
            callback: 资源变更时调用的回调函数，签名为 callback(resource_uri, content)。

        Returns:
            订阅 ID，可用于取消订阅。

        Raises:
            ValueError: 如果服务器未加载或不支持 resources 能力。
        """
        if server_name not in self.servers:
            raise ValueError(f"MCP 服务器 '{server_name}' 未加载。")

        server = self.servers[server_name]
        if not hasattr(server, "subscribe_to_resource"):
            raise ValueError(
                f"MCP 服务器 '{server_name}' 不支持 resource subscription。"
            )

        import uuid
        subscription_id = f"{server_name}:{resource_uri}:{uuid.uuid4().hex[:8]}"

        await server.subscribe_to_resource(resource_uri)

        self._resource_subscriptions[subscription_id] = {
            "server_name": server_name,
            "resource_uri": resource_uri,
            "callback": callback,
        }

        logger.info(
            f"已订阅资源 '{resource_uri}' 来自服务器 '{server_name}'，"
            f"订阅 ID: {subscription_id}。"
        )
        return subscription_id

    async def unsubscribe_from_resource(self, subscription_id: str) -> None:
        """
        取消资源订阅。

        Args:
            subscription_id: 订阅 ID，由 subscribe_to_resource 返回。

        Raises:
            ValueError: 如果订阅 ID 不存在。
        """
        if subscription_id not in self._resource_subscriptions:
            raise ValueError(f"订阅 ID '{subscription_id}' 不存在。")

        subscription = self._resource_subscriptions[subscription_id]
        server_name = subscription["server_name"]
        resource_uri = subscription["resource_uri"]

        if server_name in self.servers:
            server = self.servers[server_name]
            if hasattr(server, "unsubscribe_from_resource"):
                await server.unsubscribe_from_resource(resource_uri)

        del self._resource_subscriptions[subscription_id]

        logger.info(
            f"已取消订阅资源 '{resource_uri}'，订阅 ID: {subscription_id}。"
        )

    # ── SubTask 7.3: MCP Prompt Template Loading ──

    async def load_prompt_templates(self, server_name: str) -> list[dict]:
        """
        从 MCP 服务器加载可用的 prompt 模板。

        调用 prompts/list 方法获取服务器提供的 prompt 模板列表。

        Args:
            server_name: MCP 服务器名称。

        Returns:
            可用 prompt 模板列表，每个模板包含 name、description、arguments 等元数据。

        Raises:
            ValueError: 如果服务器未加载或不支持 prompts 能力。
        """
        if server_name not in self.servers:
            raise ValueError(f"MCP 服务器 '{server_name}' 未加载。")

        server = self.servers[server_name]
        if not hasattr(server, "list_prompts"):
            raise ValueError(f"MCP 服务器 '{server_name}' 不支持 prompts 能力。")

        prompts_result = await server.list_prompts()
        prompts_list = []

        for prompt in prompts_result.prompts:
            prompt_info = {
                "name": prompt.name,
                "description": prompt.description or "",
                "arguments": [
                    {
                        "name": arg.name,
                        "description": arg.description or "",
                        "required": getattr(arg, "required", False),
                    }
                    for arg in (prompt.arguments or [])
                ],
            }
            prompts_list.append(prompt_info)

        logger.info(
            f"从 MCP 服务器 '{server_name}' 加载了 {len(prompts_list)} 个 prompt 模板。"
        )
        return prompts_list

    async def render_prompt(
        self,
        server_name: str,
        prompt_name: str,
        arguments: dict,
    ) -> str:
        """
        使用给定的参数渲染 prompt 模板。

        调用 prompts/get 方法获取渲染后的 prompt 内容。

        Args:
            server_name: MCP 服务器名称。
            prompt_name: prompt 模板名称。
            arguments: 用于渲染的参数键值对。

        Returns:
            渲染后的 prompt 字符串。

        Raises:
            ValueError: 如果服务器未加载或不支持 prompts 能力。
        """
        if server_name not in self.servers:
            raise ValueError(f"MCP 服务器 '{server_name}' 未加载。")

        server = self.servers[server_name]
        if not hasattr(server, "get_prompt"):
            raise ValueError(f"MCP 服务器 '{server_name}' 不支持 prompts 能力。")

        result = await server.get_prompt(prompt_name, arguments)

        rendered_parts = []
        for message in result.messages:
            if hasattr(message, "content"):
                content = message.content
                if isinstance(content, str):
                    rendered_parts.append(content)
                elif hasattr(content, "text"):
                    rendered_parts.append(content.text)
                else:
                    rendered_parts.append(str(content))

        rendered = "\n".join(rendered_parts)

        logger.info(
            f"已渲染 prompt '{prompt_name}' 来自服务器 '{server_name}'。"
        )
        return rendered
