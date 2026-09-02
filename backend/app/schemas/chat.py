import datetime
from typing import Optional, List, Any
from pydantic import BaseModel


class ChatMessageCreate(BaseModel):
    lead_id: int
    content: str
    msg_type: str = "text"
    douyin_account_id: Optional[int] = None


class ChatMessageOut(BaseModel):
    id: int
    lead_id: int
    douyin_account_id: int
    direction: str
    content: str
    msg_type: str
    sent_at: datetime.datetime
    status: str

    class Config:
        from_attributes = True


class ChatSessionOut(BaseModel):
    lead_id: int
    lead_nickname: str
    lead_uid: str
    last_message: Optional[str] = None
    last_message_at: Optional[datetime.datetime] = None
    unread_count: int = 0
    chat_status: int = 0  # 0=待处理, 1=人工服务, 2=AI托管
    chat_id: Optional[str] = None
    assigned_to: Optional[int] = None
    assigned_to_name: Optional[str] = None

    class Config:
        from_attributes = True


class DouyinAccountCreate(BaseModel):
    douyin_uid: str
    nickname: str
    cookie_data: str
    proxy_url: str = ""
    nurture_enabled: bool = False
    is_new_account: bool = True


class DouyinAccountOut(BaseModel):
    id: int
    douyin_uid: str
    nickname: str
    login_status: str
    proxy_url: str = ""
    nurture_enabled: bool = False
    assigned_to_user_id: Optional[int] = None
    assigned_to_username: Optional[str] = None
    last_active_at: Optional[datetime.datetime] = None
    created_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class DouyinAccountAssign(BaseModel):
    user_id: int


class DouyinAccountCookieUpdate(BaseModel):
    cookie_data: str


class QrLoginStartOut(BaseModel):
    login_session_id: str
    qr_image_base64: str
    expires_in: int


class QrLoginStatusOut(BaseModel):
    status: str  # pending / confirmed / expired / need_verification
    cookie_data: Optional[str] = None  # 登录成功后的storage_state JSON，供add_account使用
    qr_image_base64: Optional[str] = None  # pending时可能带上刷新后的二维码(抖音端会自动更换二维码)
    verify_message: Optional[str] = None  # need_verification时的提示文案(如脱敏手机号)
    verify_image_base64: Optional[str] = None  # need_verification时的当前页面截图


class QrVerifyCodeIn(BaseModel):
    code: str
