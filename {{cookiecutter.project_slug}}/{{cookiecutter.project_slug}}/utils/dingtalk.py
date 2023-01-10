import hashlib
import json as jsonlib
import typing
from urllib.parse import urljoin

import httpx
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import APIException, ParseError, ValidationError

__all__ = ["DingtalkCorpAPI"]


class APIServerError(APIException):
    default_detail = _("接口内部异常")
    default_code = "system_error"


class APIParseError(ParseError):
    default_detail = _("数据解析错误")
    default_code = "parse_error"


class APIRequestError(ValidationError):
    default_detail = _("请求参数异常")
    default_code = "invalid_params"


class APIRequestProxyClient:
    def __init__(self, *args, **kwargs) -> None:
        self._client = self.get_client(*args, **kwargs)

    def get_client(self, *args, **kwargs) -> typing.Any:
        raise NotImplementedError()

    def _request(self, method: str, url: str, *args, **kwargs) -> dict[str, typing.Any]:
        raise NotImplementedError()

    @typing.final
    def get(self, url: str, params: dict = None, **kwargs) -> dict[str, typing.Any]:
        return self._request("get", url, params=params, **kwargs)

    @typing.final
    def post(self, url: str, params: dict = None, json: dict = None, **kwargs) -> dict[str, typing.Any]:
        return self._request("post", url, params=params, json=json, **kwargs)


class HTTPXProxyClient(APIRequestProxyClient):
    def get_client(self, *args, **kwargs) -> httpx.Client:
        return httpx.Client(http2=True)

    def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> dict[str, typing.Any]:

        resp: httpx.Response = getattr(self._client, method)(url, **kwargs)
        try:
            json_data = resp.json()
        except jsonlib.JSONDecodeError:
            raise APIParseError()

        if resp.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            raise APIServerError(json_data["message"])
        elif resp.status_code >= status.HTTP_400_BAD_REQUEST:
            raise APIRequestError(json_data["message"])

        # 兼容钉钉新版及旧版api
        if "errmsg" in json_data and (errmsg := json_data["errmsg"]) != "ok":
            raise APIRequestError(errmsg)

        return json_data


class DingtalkCorpAPI:
    """
    钉钉企业内部应用接口SDK
    兼容新版及旧版API
    """

    _cache_key_prefix: str = "dingtalk:"
    default_client_class = HTTPXProxyClient
    api_server: str = "https://oapi.dingtalk.com"
    new_api_server: str = "https://api.dingtalk.com"
    agent_id_param_name: str = "DINGTALK_AGENT_ID"
    app_key_param_name: str = "DINGTALK_APP_KEY"
    app_secret_param_name: str = "DINGTALK_APP_SECRET"

    def __init__(
        self,
        agent_id: str = None,
        app_key: str = None,
        app_secret: str = None,
        client: APIRequestProxyClient = None,
    ) -> None:
        self._access_token = None
        self._client = client or self.default_client_class()
        self._agent_id = agent_id or getattr(settings, self.agent_id_param_name, None)
        self._app_key = app_key or getattr(settings, self.app_key_param_name, None)
        self._app_secret = app_secret or getattr(settings, self.app_secret_param_name, None)
        if not self._agent_id or not self._app_key or not self._app_secret:
            raise ImproperlyConfigured(
                "You must set `DINGTALK_APP_KEY`, `DINGTALK_APP_SECRET` and `DINGTALK_AGENT_ID` in settings.py"
            )

    @property
    def _corp_app_id(self) -> str:
        s = f"{self._agent_id}:{self._app_key}:{self._app_secret}".encode()
        return self._cache_key_prefix + hashlib.md5(s).hexdigest()

    def get_url(self, path: str) -> str:
        return urljoin(self.api_server, path)

    def get_new_url(self, path: str) -> str:
        return urljoin(self.new_api_server, path)

    @staticmethod
    def remove_blank_params(params: typing.Mapping[str, typing.Any]) -> dict[str, typing.Any]:
        return {k: v for k, v in params.items() if v is not None}

    @property
    def access_token(self) -> str:
        """
        企业应用凭证用于调用服务端API
        :return: 企业微应用访问凭证token
        """
        access_token = cache.get(self._corp_app_id)
        if not access_token:
            access_token, expires_in = self.get_access_token()
            cache.set(self._corp_app_id, access_token, timeout=expires_in)

        return access_token

    def get_access_token(self, app_key: str = None, app_secret: str = None) -> tuple[str, int]:
        """
        获取企内部应用access token
        接口文档: https://open.dingtalk.com/document/orgapp-server/obtain-orgapp-token
        :param app_key: 应用的唯一标识key
        :param app_secret: 应用的密钥。AppKey和AppSecret可在钉钉开发者后台的应用详情页面获取。
        :return: 企业微应用访问凭证,凭证到期时间(单位:秒)
        """
        path = "/gettoken"
        params = {
            "appkey": app_key or self._app_key,
            "appsecret": app_secret or self._app_secret,
        }
        ret = self._client.get(self.get_url(path), params=params)
        return ret["access_token"], ret["expires_in"]

    def get_user_info_by_code(self, code: str, access_token: str = None) -> dict[str, typing.Union[int, str, bool]]:
        """
        通过免登码获取用户ID等信息
        接口文档: https://open.dingtalk.com/document/orgapp-server/obtain-the-userid-of-a-user-by-using-the-log-free
        :param code: 用户免登授权码 微应用获取参考: https://open.dingtalk.com/document/isvapp-client/logon-free-process
        :param access_token: 调用服务端API的应用凭证
        :return: 用户信息 userid,device_id,unionid,name,associated_unionid,sys_level,sys
        """
        path = "/topapi/v2/user/getuserinfo"
        params = {"access_token": access_token or self.access_token}
        json = {"code": code}
        ret = self._client.post(self.get_url(path), params=params, json=json)
        return ret["result"]

    def get_user_id_by_mobile(
        self,
        mobile: str,
        support_exclusive_account_search: bool = None,
        access_token: str = None,
    ) -> tuple[str, typing.Optional[list[str]]]:
        """
        通过用户手机号获取用户ID
        注意: 需要微应用开通对应权限
        接口文档: https://open.dingtalk.com/document/orgapp-server/query-users-by-phone-number
        :param mobile: 手机号码
        :param support_exclusive_account_search: 是否支持通过手机号搜索专属帐号(不含其他组织创建的专属帐号)。true:支持 false:不支持
        :param access_token: 调用服务端API的应用凭证
        :return: 员工的userId, 专属帐号员工的userid列表(不含其他组织创建的专属帐号)
        """
        path = "/topapi/v2/user/getbymobile"
        params = {"access_token": access_token or self.access_token}
        json = {"mobile": mobile, "support_exclusive_account_search": support_exclusive_account_search}
        json = self.remove_blank_params(json)
        ret = self._client.post(self.get_url(path), params=params, json=json)
        return ret["result"]["userid"], ret["result"].get("exclusive_account_userid_list")

    def get_user_id_by_unionid(self, unionid: str, access_token: str = None) -> tuple[str, int]:
        """
        通过unionid获取用户ID
        注意: 需要微应用开通对应权限
        接口文档: https://open.dingtalk.com/document/orgapp-server/query-a-user-by-the-union-id
        :param unionid: 同一个企业员工，在不同的开发者企业账号下，unionid是不相同的。在同一个开发者企业账号下，unionid是唯一且不变的
        :param access_token: 调用服务端API的应用凭证
        :return: 员工的userId, 联系类型(0:企业内部员工, 1:企业外部联系人)
        """
        path = "/topapi/user/getbyunionid"
        params = {"access_token": access_token or self.access_token}
        json = {"unionid": unionid}
        ret = self._client.post(self.get_url(path), params=params, json=json)
        return ret["result"]["userid"], ret["result"]["contact_type"]

    def get_user_details(self, user_id: str, access_token: str = None) -> dict[str, typing.Any]:
        """
        通过用户ID获取用户详细信息
        注意: 需要微应用开通对应权限
        接口文档: https://open.dingtalk.com/document/orgapp-server/query-user-details
        :param user_id: 员工的userId
        :param access_token: 调用服务端API的应用凭证
        :return: 用户详细信息 userid,unionid,name,avatar,state_code,mobile,manager_userid,email,job_number...
        """
        path = "/topapi/v2/user/get"
        params = {"access_token": access_token or self.access_token}
        json = {"userid": user_id}
        ret = self._client.post(self.get_url(path), params=params, json=json)
        return ret["result"]

    def send_work_message(
        self,
        message: typing.Mapping[str, typing.Any],
        userid_list: str = None,
        dept_id_list: str = None,
        to_all_user: bool = None,
        agent_id: str = None,
        access_token: str = None,
    ) -> int:
        """
        发送工作通知
        注意: 给同一员工一天只能发送一条内容相同的消息通知, 每个员工最多可发送500条消息通知
        接口文档: https://open.dingtalk.com/document/isvapp-server/asynchronous-sending-of-enterprise-session-messages
        :param message: 通知消息 {"msgtype": "text", "text": { "content": "请提交日报。"}}
        :param userid_list: 多个用,分隔(userid_list,dept_id_list, to_all_user必须有一个不能为空)
        :param dept_id_list: 多个用,分隔(可不传，若传不能为空)
        :param to_all_user: 可选
        :param agent_id: 发送消息时使用的微应用的AgentID
        :param access_token: 调用服务端API的应用凭证
        :return: 创建的异步发送任务ID
        """
        path = "/topapi/message/corpconversation/asyncsend_v2"
        params = {"access_token": access_token or self.access_token}
        json = {
            "agent_id": agent_id or self._agent_id,
            "msg": message,
            "userid_list": userid_list,
            "dept_id_list": dept_id_list,
            "to_all_user": to_all_user,
        }
        json = self.remove_blank_params(json)
        ret = self._client.post(self.get_url(path), params=params, json=json)
        return ret["task_id"]

    def get_work_message_send_result(
        self,
        task_id: int,
        agent_id: str = None,
        access_token: str = None,
    ) -> dict[str, list]:
        """
        获取工作通知发送结果
        注意: 通过接口发送工作通知，当接收人列表超过100人时，不支持调用该接口，否则系统会返回调用超时
        接口文档: https://open.dingtalk.com/document/orgapp-server/gets-the-result-of-sending-messages-asynchronously-to-the-enterprise
        :param task_id: 发送消息时钉钉返回的任务ID
        :param agent_id: 发送消息时使用的微应用的AgentID
        :param access_token: 调用服务端API的应用凭证
        :return: 工作通知消息的发送结果
        """  # noqa: E501
        path = "/topapi/message/corpconversation/getsendresult"
        params = {"access_token": access_token or self.access_token}
        json = {"agent_id": agent_id or self._agent_id, "task_id": task_id}
        ret = self._client.post(self.get_url(path), params=params, json=json)
        return ret["send_result"]

    def recall_work_message(
        self,
        task_id: int,
        agent_id: str = None,
        access_token: str = None,
    ) -> None:
        """
        撤回工作通知
        接口文档: https://open.dingtalk.com/document/orgapp-server/notification-of-work-withdrawal
        :param task_id: 发送消息时钉钉返回的任务ID
        :param agent_id: 发送消息时使用的微应用的AgentID
        :param access_token: 调用服务端API的应用凭证
        :return: None
        """
        path = "/topapi/message/corpconversation/recall"
        params = {"access_token": access_token or self.access_token}
        json = {"msg_task_id": task_id, "agent_id": agent_id or self._agent_id}
        self._client.post(self.get_url(path), params=params, json=json)

    def add_todo_task(
        self,
        subject: str,
        unionid: str,
        operator_id: str = None,
        source_id: str = None,
        creator_id: str = None,
        executor_ids: list[str] = None,
        participant_ids: list[str] = None,
        description: str = None,
        due_time: int = None,
        detail_url: typing.Mapping[str, typing.Any] = None,
        is_only_show_executor: bool = None,
        priority: int = None,
        notify_configs: typing.Mapping[str, typing.Any] = None,
        access_token: str = None,
    ) -> dict[str, typing.Any]:
        """
                调用本接口发起一个钉钉待办任务
                该待办事项会出现在钉钉客户端“待办事项”页面。
                注意: 需要微应用开通对应权限 -> 待办应用中待办写权限
                接口文档: https://open.dingtalk.com/document/orgapp-server/add-dingtalk-to-do-task
                :param subject: 待办标题，最大长度1024
                :param unionid: 当前访问资源所归属用户的unionId，和创建者的unionId保持一致。
                :param operator_id: 当前操作者用户的unionId。
                :param source_id: 业务系统侧的唯一标识ID，即业务ID。 当ISV接入钉钉待办后，传递ISV应用业务系统侧的唯一标识任务ID。当待办创建成功后，需要更换新的sourceId，保持一个待办任务对应一个sourceId。 # noqa
        创建钉钉官方待办时，该字段无需传入。
                :param creator_id: 创建者的unionId。
                :param executor_ids: 执行者的unionId，最大数量1000。
                :param participant_ids: 参与者的unionId，最大数量1000。
                :param description: 待办备注描述，最大长度4096。
                :param due_time: 截止时间，Unix时间戳，单位毫秒。
                :param detail_url: 详情页url跳转地址。 创建钉钉官方待办时，该字段无需传入。创建第三方待办时，需传入自身应用详情页链接。
                :param is_only_show_executor: 生成的待办是否仅展示在执行者的待办列表。
                :param priority: 优先级，取值：10：较低， 20：普通， 30：紧急， 40：非常紧急
                :param notify_configs: 待办通知配置。
                :param access_token:
                :return:
        """
        path = f"/v1.0/todo/users/{unionid}/tasks"
        headers = {"x-acs-dingtalk-access-token": access_token or self.access_token}
        params = {}
        if operator_id:
            params["operatorId"] = operator_id

        json = {
            "subject": subject,
            "sourceId": source_id,
            "creatorId": creator_id,
            "description": description,
            "dueTime": due_time,
            "executorIds": executor_ids,
            "participantIds": participant_ids,
            "detailUrl": detail_url,
            "isOnlyShowExecutor": is_only_show_executor,
            "priority": priority,
            "notifyConfigs": notify_configs,
        }
        json = self.remove_blank_params(json)
        ret = self._client.post(self.get_new_url(path), params=params, json=json, headers=headers)
        return ret

    def create_group_chat(
        self,
        name: str,
        owner: str,
        userid_list: list[str],
        show_history_type: int = None,
        searchable: int = None,
        validation_type: int = None,
        mention_all_authority: int = None,
        management_type: int = None,
        chat_banned_type: int = None,
        access_token: str = None,
    ) -> tuple[str, typing.Optional[str], int]:
        """
        创建群会话
        注意: 需要微应用开通对应权限
        接口文档: https://open.dingtalk.com/document/orgapp-server/create-group-session
        :param name: 群名称，长度限制为1~20个字符
        :param owner: 群主的userid
        :param userid_list: 群成员列表，每次最多支持40人，群人数上限为1000
        :param show_history_type: 新成员是否可查看100条历史消息：0(默认)：不可查看 1：可查看
        :param searchable: 群是否可以被搜索：0(默认)：不可搜索 1：可搜索
        :param validation_type: 入群是否需要验证：0(默认)：不验证 1：入群验证
        :param mention_all_authority: @all 使用范围： 0(默认)：所有人 1：仅群主
        :param management_type: 群管理类型： 0(默认)：所有人可以管理 1：仅群主可管理
        :param chat_banned_type: 是否开启群禁言：0(默认)：不禁言 1：全员禁言
        :param access_token: 调用服务端API授权凭证
        :return: openConversationId(群会话的ID), chatid(群会话的ID,即将废弃), conversationTag(会话类型, 2:企业群)
        """
        path = "/chat/create"
        params = {"access_token": access_token or self.access_token}
        json = {
            "name": name,
            "owner": owner,
            "useridlist": userid_list,
            "show_history_type": show_history_type,
            "searchable": searchable,
            "validation_type": validation_type,
            "mention_all_authority": mention_all_authority,
            "management_type": management_type,
            "chat_banned_type": chat_banned_type,
        }
        json = self.remove_blank_params(json)
        ret = self._client.post(self.get_url(path), params=params, json=json)
        return ret["openConversationId"], ret.get("chatid"), ret["conversationTag"]

    def modify_group_chat(
        self,
        chatid: str,
        name: str = None,
        owner: str = None,
        owner_type: str = None,
        add_userid_list: list[str] = None,
        del_userid_list: list[str] = None,
        add_extidlist: list[str] = None,
        del_extidlist: list[str] = None,
        icon: str = None,
        searchable: int = None,
        validation_type: int = None,
        mention_all_authority: int = None,
        management_type: int = None,
        chat_banned_type: int = None,
        show_history_type: int = None,
        access_token: str = None,
    ) -> None:
        """
        修改群会话
        注意: 需要微应用开通对应权限
        接口文档: https://open.dingtalk.com/document/orgapp-server/modify-a-group-session
        :param chatid: 群会话ID
        :param name: 群名称，长度限制为1~20个字符
        :param owner: 群主的userid
        :param owner_type: 群主类型：emp：企业员工 ext：外部联系人
        :param add_userid_list: 添加的群成员列表，每次最多支持40人，群人数上限为1000
        :param del_userid_list: 删除的成员列表
        :param add_extidlist: 添加的外部联系人成员列表
        :param del_extidlist: 删除的外部联系人成员列表
        :param icon: 群头像的mediaId
        :param searchable: 群是否可以被搜索：0(默认)：不可搜索 1：可搜索
        :param validation_type: 入群是否需要验证：0(默认)：不验证 1：入群验证
        :param mention_all_authority: @all 使用范围： 0(默认)：所有人 1：仅群主
        :param management_type: 群管理类型： 0(默认)：所有人可以管理 1：仅群主可管理
        :param chat_banned_type: 是否开启群禁言：0(默认)：不禁言 1：全员禁言
        :param show_history_type: 新成员是否可查看100条历史消息：0(默认)：不可查看 1：可查看
        :param access_token: 调用服务端API授权凭证
        :return: None
        """
        path = "/chat/update"
        params = {"access_token": access_token or self.access_token}
        json = {
            "chatid": chatid,
            "name": name,
            "owner": owner,
            "owner_type": owner_type,
            "add_userid_list": add_userid_list,
            "del_userid_list": del_userid_list,
            "add_extidlist": add_extidlist,
            "del_extidlist": del_extidlist,
            "icon": icon,
            "show_history_type": show_history_type,
            "searchable": searchable,
            "validation_type": validation_type,
            "mention_all_authority": mention_all_authority,
            "management_type": management_type,
            "chat_banned_type": chat_banned_type,
        }
        json = self.remove_blank_params(json)
        self._client.post(self.get_url(path), params=params, json=json)
