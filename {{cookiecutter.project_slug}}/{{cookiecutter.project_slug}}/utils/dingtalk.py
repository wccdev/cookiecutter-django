import hashlib
import json as jsonlib
import time
import typing
from urllib.parse import urljoin

import requests
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

    @typing.final
    def put(self, url: str, params: dict = None, json: dict = None, **kwargs) -> dict[str, typing.Any]:
        return self._request("put", url, params=params, json=json, **kwargs)

    @typing.final
    def patch(self, url: str, params: dict = None, json: dict = None, **kwargs) -> dict[str, typing.Any]:
        return self._request("patch", url, params=params, json=json, **kwargs)


class RequestsProxyClient(APIRequestProxyClient):
    def get_client(self, *args, **kwargs) -> requests.Session:
        return requests.Session()

    def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> dict[str, typing.Any]:
        resp: requests.Response = getattr(self._client, method)(url, **kwargs)
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
    default_client_class = RequestsProxyClient
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
            cache.set(self._corp_app_id, access_token, timeout=expires_in - 100)

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

    def get_user_access_token(
        self, auth_code: str, refresh_token: str = None, grant_type: str = "authorization_code"
    ) -> dict[str, typing.Any]:
        """
        获取用户访问凭证
        接口文档: https://open.dingtalk.com/document/isvapp-server/obtain-user-token
        :param auth_code: OAuth 2.0 临时授权码。
        :param refresh_token: OAuth2.0刷新令牌，从返回结果里面获取
        :param grant_type: 授权类型
        :return: accessToken,refreshToken,expireIn,corpId
        """
        path = "/v1.0/oauth2/userAccessToken"
        json = {
            "clientId": self._app_key,
            "clientSecret": self._app_secret,
            "code": auth_code,
            "refreshToken": refresh_token,
            "grantType": grant_type,
        }
        return self._client.post(self.get_new_url(path), json=self.remove_blank_params(json))

    def get_user_contact_info(self, unionid: str, access_token: str = None) -> dict[str, typing.Any]:
        """
        获取企业用户通讯录中的个人信息
        :param unionid: 用户的unionId, me获取当前用户
        :param access_token: 调用服务端接口的授权凭证
        :return: nick,avatarUrl,mobile,openId,email,unionId,stateCode
        """
        path = f"/v1.0/contact/users/{unionid}"
        headers = {"x-acs-dingtalk-access-token": access_token or self.access_token}
        return self._client.get(self.get_new_url(path), headers=headers)

    def get_user_info_by_code(self, code: str, access_token: str = None) -> dict[str, int | str | bool]:
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
    ) -> tuple[str, list[str] | None]:
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
        :param source_id: 业务系统侧的唯一标识ID，即业务ID。 当ISV接入钉钉待办后，传递ISV应用业务系统侧的唯一标识任务ID。当待办创建成功后，需要更换新的sourceId，保持一个待办任务对应一个sourceId。创建钉钉官方待办时，该字段无需传入。 # noqa
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
    ) -> tuple[str, str | None, int]:
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

    def robot_send_interactive_cards(
        self,
        card_data: dict,
        single_chat_receiver: dict = None,
        open_conversation_id: str = None,
        card_biz_id: str = None,
        card_template_id: str = "StandardCard",
        callback_url: str = None,
        userid_private_data_map: dict = None,
        unionid_private_data_map: dict = None,
        send_options: dict = None,
        pull_strategy: bool = None,
        robot_code: str = None,
        access_token: str = None,
    ) -> tuple[str, str]:
        """
        机器人发送互动卡片（普通版）
        接口文档: https://open.dingtalk.com/document/orgapp/robots-send-interactive-cards
        :param card_data: 卡片模板文本内容参数，卡片json结构体。
        :param single_chat_receiver: 单聊会话接收者json串。
        :param open_conversation_id: 接收卡片的加密群ID，特指多人群会话（非单聊）。
        :param card_biz_id: 唯一标识一张卡片的外部ID，卡片幂等ID，可用于更新或重复发送同一卡片到多个群会话。
        :param card_template_id: 卡片搭建平台模板ID，固定值填写为StandardCard
        :param callback_url: 可控制卡片回调的URL，不填则无需回调。
        :param userid_private_data_map: 卡片模板userId差异用户参数，json结构体。
        :param unionid_private_data_map: 卡片模板unionId差异用户参数，json结构体。
        :param send_options: 互动卡片发送选项。
        :param pull_strategy: 是否开启卡片纯拉模式。
        :param robot_code: 机器人的编码。默认和应用app_key相同
        :param access_token: 调用服务端API授权凭证
        :return process_query_key: 用于业务方后续查看已读列表的查询key。 card_biz_id: 卡片id
        """
        path = "/v1.0/im/v1.0/robot/interactiveCards/send"
        headers = {"x-acs-dingtalk-access-token": access_token or self.access_token}

        if robot_code is None and self._agent_id is None:
            raise ImproperlyConfigured("You must provide 'robot_code' or set 'agent_id'")

        if card_biz_id is None:
            card_biz_id = f"card-{int(time.time() * 1000)}"

        if card_data:
            card_data = jsonlib.dumps(card_data)

        if single_chat_receiver:
            single_chat_receiver = jsonlib.dumps(single_chat_receiver)

        if userid_private_data_map:
            userid_private_data_map = jsonlib.dumps(userid_private_data_map)

        if unionid_private_data_map:
            unionid_private_data_map = jsonlib.dumps(unionid_private_data_map)

        json = {
            "cardTemplateId": card_template_id,
            "cardBizId": card_biz_id,
            "robotCode": robot_code or self._app_key,
            "cardData": card_data,
            "openConversationId": open_conversation_id,
            "singleChatReceiver": single_chat_receiver,
            "callbackUrl": callback_url,
            "userIdPrivateDataMap": userid_private_data_map,
            "unionIdPrivateDataMap": unionid_private_data_map,
            "sendOptions": send_options,
            "pullStrategy": pull_strategy,
        }
        json = self.remove_blank_params(json)
        ret = self._client.post(self.get_new_url(path), headers=headers, json=json)
        return ret["processQueryKey"], card_biz_id

    def robot_update_interactive_cards(
        self,
        card_biz_id: str,
        card_data: dict = None,
        userid_private_data_map: dict = None,
        unionid_private_data_map: dict = None,
        update_options: dict = None,
        access_token: str = None,
    ) -> str:
        """
        更新机器人发送互动卡片（普通版）
        接口文档: https://open.dingtalk.com/document/orgapp/update-the-robot-to-send-interactive-cards
        :param card_biz_id: 唯一标识一张卡片的外部ID，卡片幂等ID，可用于更新或重复发送同一卡片到多个群会话。
        :param card_data: 卡片模板文本内容参数，卡片json结构体。
        :param userid_private_data_map:
            卡片模板userId差异用户参数，json结构体，表示特殊消息接收人接收卡片的具体内容信息。
            例如：群主为userId为userId0001，需要展示不同与普通群员cardData的数据内容信息，可以使用userIdPrivateDataMap实现数据差异化。
            参数格式为："{"userId值":{卡片消息cardData参数值}}"
        :param unionid_private_data_map: 卡片模板unionId差异用户参数，json结构体。
        :param update_options: 互动卡片发送选项。
        :param access_token: 调用服务端API授权凭证
        :return process_query_key: 用于业务方后续查看已读列表的查询key。
        """
        path = "/v1.0/im/robots/interactiveCards"
        headers = {"x-acs-dingtalk-access-token": access_token or self.access_token}

        if card_data:
            card_data = jsonlib.dumps(card_data)

        if userid_private_data_map:
            userid_private_data_map = jsonlib.dumps(userid_private_data_map)

        if unionid_private_data_map:
            unionid_private_data_map = jsonlib.dumps(unionid_private_data_map)

        json = {
            "cardBizId": card_biz_id,
            "cardData": card_data,
            "userIdPrivateDataMap": userid_private_data_map,
            "unionIdPrivateDataMap": unionid_private_data_map,
            "updateOptions": update_options,
        }
        json = self.remove_blank_params(json)
        ret = self._client.put(self.get_new_url(path), headers=headers, json=json)
        return ret["processQueryKey"]

    def send_interactive_cards(
        self,
        card_template_id: str,
        card_data: dict,
        conversation_type: int,
        open_conversation_id: string = None,
        userid_type: int = None,
        receiver_userid_list: list[str] = None,
        at_openids: dict = None,
        out_track_id: str = None,
        robot_code: str = None,
        chatbot_id: str = None,
        callback_route_key: str = None,
        private_data_map: dict = None,
        card_options: dict = None,
        pull_strategy: bool = None,
        access_token: str = None,
    ) -> tuple[str, str]:
        """
        发送互动卡片（高级版，支持通过平台配置模版）
        注意: 需要开通 chat相关接口的管理权限！
        接口文档: https://open.dingtalk.com/document/orgapp/send-interactive-dynamic-cards-1
        特殊使用场景说明：
          场景群机器人发送：场景群使用robotCode来发送，chatBotId不填写。
          非场景群企业机器人发送：填写robotCode来发送，chatBotId不填写。
          非场景群机器人单聊发送：chatBotId和robotCode都不填写，直接用支持单聊的机器人应用来发送。

        :param card_template_id: 卡片搭建平台模板ID
        :param card_data: 卡片模板文本内容参数，卡片json结构体。
        :param conversation_type: 发送的会话类型：0：单聊 1：群聊。receiverUserIdList填写用户ID，最大支持20个
        :param open_conversation_id: 群ID：1.基于群模板创建的群 2.安装群聊酷应用的群。 单聊时不用填写
        :param userid_type: 用户ID类型：1（默认）：userid模式 2：unionId模式
        :param receiver_userid_list: 接收人userId列表, 单聊: 填写用户ID，最大支持20个; 群聊：填写用户ID,表示当前对应ID的群内用户可见. 不填写，表示当前群内所有用户可见
        :param at_openids: 消息@人。格式：{"key":"value"}。key：用户ID，根据userid_type设置。value：用户名。 例如：{"123456": "钉三多"}
        :param out_track_id: 唯一标示卡片的外部编码。是由开发者自己生成并作为入参传递给钉钉的。 一般情况下，如果使用了新的 cardTemplateId 或 cardData 等参数，则需要生成一个全新的 outTrackId，否则更改不会生效  # noqa
        :param robot_code: 机器人的编码。默认和应用app_key相同
          场景群机器人发送：场景群使用robotCode来发送，chatBotId不填写。
          非场景群企业机器人发送：填写robotCode来发送，chatBotId不填写。
          非场景群机器人单聊发送：chatBotId和robotCode都不填写，直接用支持单聊的机器人应用来发送。
        :param chatbot_id: 同上
        :param callback_route_key: 卡片回调时的路由Key，用于查询注册的callbackUrl。
        :param private_data_map: 卡片模板userId差异用户参数，json结构体。
        :param card_options: 卡片操作。
        :param pull_strategy: 是否开启卡片纯拉模式。
        :param access_token: 调用服务端API授权凭证
        :return (process_query_key, out_track_id): 用于业务方后续查看已读列表的查询key。 out_track_id: 卡片id
        """
        path = "/v1.0/im/interactiveCards/send"
        headers = {"x-acs-dingtalk-access-token": access_token or self.access_token}

        if robot_code is None and self._agent_id is None:
            raise ImproperlyConfigured("You must provide 'robot_code' or set 'agent_id'")

        if out_track_id is None:
            out_track_id = f"card-{int(time.time() * 1000)}"

        json = {
            "cardTemplateId": card_template_id,
            "openConversationId": card_biz_id,
            "receiverUserIdList": robot_code or self._app_key,
            "outTrackId": card_data,
            "robotCode": open_conversation_id,
            "conversationType": single_chat_receiver,
            "callbackRouteKey": callback_url,
            "cardData": userid_private_data_map,
            "privateData": unionid_private_data_map,
            "chatBotId": send_options,
            "userIdType": pull_strategy,
            "atOpenIds": "",
            "cardOptions": "",
            "pullStrategy": "",
        }
        json = self.remove_blank_params(json)
        ret = self._client.post(self.get_new_url(path), headers=headers, json=json)
        return ret["processQueryKey"], card_biz_id

    def update_interactive_cards(
        self,
        out_track_id: str,
        card_data: dict = None,
        private_data: dict[str, dict] = None,
        userid_type: dict = None,
        card_options: dict = None,
        access_token: str = None,
    ) -> str:
        """
        更新互动卡片
        接口文档: https://open.dingtalk.com/document/orgapp/update-dingtalk-interactive-cards-1
        :param out_track_id: 卡片的唯一标识编码。
        :param card_data: 卡片数据。
        :param private_data: 指定用户可见的按钮列表。
        :param userid_type: 用户ID类型：
        :param card_options: 发送可交互卡片的功能选项。
        :param access_token: 调用服务端API授权凭证
        :return success: 更新结果。
        """
        path = "/v1.0/im/interactiveCards"
        headers = {"x-acs-dingtalk-access-token": access_token or self.access_token}
        json = {
            "outTrackId": out_track_id,
            "cardData": card_data,
            "privateData": private_data,
            "userIdType": userid_type,
            "cardOptions": card_options,
        }
        json = self.remove_blank_params(json)
        ret = self._client.put(self.get_new_url(path), headers=headers, json=json)
        return ret["success"]

    def upload_media_file(self, type: str, file: str, access_token: str = None) -> tuple[str, str, str]:
        """
        钉钉上传媒体文件（上传的媒体文件公共读）
        接口文档: https://open.dingtalk.com/document/orgapp/upload-media-files
        :param type: 媒体文件类型：
            image：图片，图片最大20MB。支持上传jpg、gif、png、bmp格式。
            voice：语音，语音文件最大2MB。支持上传amr、mp3、wav格式。
            video：视频，视频最大20MB。支持上传mp4格式。
            file：普通文件，最大20MB。支持上传doc、docx、xls、xlsx、ppt、pptx、zip、pdf、rar格式。
        :param file: 要上传的媒体文件。form-data中媒体文件标识，有filename、filelength、content-type等信息。
        :param access_token: 卡片模板文本内容参数，卡片json结构体。
        :param access_token: 调用服务端API授权凭证
        :return media_id,type,created_at
        """
        path = "/media/upload"
        params = {"access_token": access_token or self.access_token}

        if type not in ("image", "voice", "video", "file"):
            raise ValueError(f"type: {type} not in allowed list")

        with open(file, "rb") as fo:
            files = {"media": fo}
            data = {"type": type}
            ret = self._client.post(self.get_url(path), params=params, data=data, files=files)

        return ret["media_id"], ret["type"], ret["created_at"]
