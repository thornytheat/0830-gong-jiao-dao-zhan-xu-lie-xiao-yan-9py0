from flask import jsonify

LABELS = {
    'FILE_TOO_LARGE':'文件超过 256 KiB', 'FILE_EMPTY':'文件没有内容', 'FILE_BLANK':'文件只有空白',
    'HEADER_ONLY':'文件只有标题行', 'HEADER_MISMATCH':'列名与字段字典不一致', 'ENCODING_INVALID':'请使用 UTF-8 CSV',
    'CSV_MALFORMED':'CSV 引号或行格式异常', 'ROW_LIMIT':'文件超过 2000 行', 'FILE_REQUIRED':'请选择 CSV 文件',
    'RUN_NOT_FOUND':'批次不存在', 'REVIEW_FIELDS':'请填写 3 至 200 字复核意见', 'STALE_REVIEW':'批次已更新，请刷新',
    'RUN_FINALIZED':'批次已签发', 'UNRESOLVED_ISSUES':'存在待处理差异', 'SAMPLE_UNKNOWN':'样例不存在', 'STAGE_UNKNOWN':'处理阶段不存在',
    'INVALID_CONFIRMATION':'人工确认点无效：站点需属于班次站序，时点不能超过班次截止',
    'CONFIRMATION_CONFLICT':'确认点时间与站序冲突，班次暂缓', 'CONFIRMATION_EXISTS':'确认点已登记',
    'CONFIRMATION_NOT_FOUND':'确认点不存在或已撤回', 'CONFIRMATION_CASE_UNKNOWN':'业务组不存在',
}


def response(error):
    code = error.code
    status = 404 if code in {'RUN_NOT_FOUND','SAMPLE_UNKNOWN','STAGE_UNKNOWN','CONFIRMATION_NOT_FOUND','CONFIRMATION_CASE_UNKNOWN'} else 409 if code in {'STALE_REVIEW','RUN_FINALIZED','UNRESOLVED_ISSUES','CONFIRMATION_CONFLICT','CONFIRMATION_EXISTS'} else 413 if code=='FILE_TOO_LARGE' else 422
    return jsonify(code=code,message=LABELS.get(code,code)),status
