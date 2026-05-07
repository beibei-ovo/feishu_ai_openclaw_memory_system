"""飞书 API 客户端 - 用于发送回复消息"""
import requests
import json
import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


class FeishuClient:
    """飞书 API 客户端"""
    
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.tenant_access_token = None
        self.token_expire_time = 0
    
    def _get_tenant_access_token(self) -> str:
        """获取 tenant_access_token"""
        if self.tenant_access_token and self.token_expire_time > 0:
            # 检查 token 是否还有效
            import time
            if time.time() < self.token_expire_time:
                return self.tenant_access_token
        
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
        result = response.json()
        
        if result.get("code") == 0:
            self.tenant_access_token = result.get("tenant_access_token")
            import time
            self.token_expire_time = time.time() + result.get("expire", 7200) - 300  # 提前5分钟过期
            return self.tenant_access_token
        else:
            raise Exception(f"获取 tenant_access_token 失败: {result}")
    
    def send_message(self, receive_id: str, content: str, receive_id_type: str = "open_id"):
        """
        发送消息
        
        Args:
            receive_id: 接收者ID
            content: 消息内容
            receive_id_type: 接收者ID类型，默认为 open_id
        """
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        token = self._get_tenant_access_token()
        
        # 构造消息内容
        message_content = json.dumps({
            "text": content
        })
        
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": message_content
        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(url, json=payload, headers=headers, params={"receive_id_type": receive_id_type})
        result = response.json()
        
        # 安全打印，避免编码问题
        safe_content = content.encode('ascii', 'ignore').decode('ascii')
        print(f"发送消息到飞书: receive_id={receive_id}, content={safe_content[:50]}...")
        
        if result.get("code") != 0:
            print(f"发送消息失败: {result}")
            return False
        
        return True


# 创建一个模拟的飞书客户端，用于本地测试
class MockFeishuClient(FeishuClient):
    """模拟飞书客户端 - 只打印消息，不实际发送"""
    
    def __init__(self):
        super().__init__("mock_id", "mock_secret")
    
    def send_message(self, receive_id: str, content: str, receive_id_type: str = "open_id"):
        safe_content = content.encode('ascii', 'ignore').decode('ascii')
        print(f"[Mock] Sending message to {receive_id}: {safe_content}")
        return True


# 工厂函数，创建飞书客户端
def create_feishu_client() -> FeishuClient:
    """创建飞书客户端 - 根据环境变量决定使用真实还是模拟"""
    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")
    
    if app_id and app_secret:
        print("Using real Feishu client")
        return FeishuClient(app_id, app_secret)
    else:
        print("Using mock Feishu client (please set FEISHU_APP_ID and FEISHU_APP_SECRET)")
        return MockFeishuClient()