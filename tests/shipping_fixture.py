"""真实HTTP测试共用的收货准备；只使用自有测试用户，通过公开地址/快照接口。"""


def prepare_shipping(call, token, activity, sku, request):
    code, result = call('GET', '/api/shop/addresses', token=token)[:2]
    assert code == 200, result
    if result['items']:
        aid = result['items'][0]['id']
    else:
        code, result = call('POST', '/api/shop/addresses',
                            {'recipient': '测试收货人', 'phone': '13800138000',
                             'address': '测试收货地址100号 不寄送实物'}, token)[:2]
        assert code == 200, result
        aid = result['id']
    code, result = call('POST', '/api/shop/seckill/checkout',
                        {'activityId': str(activity), 'skuId': str(sku),
                         'requestId': request, 'addressId': aid}, token)[:2]
    assert code == 200, result
    return aid
