"""S19 gate rejects short, incomplete and internally inconsistent reports."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_journey_gate import evaluate
from load_s19_journeys import accessible_answer, aggregate, LIMITS


def inventory(activity, initial, held, orders):
    return {'activityId':str(activity),'status':'CLEAN','readOnly':True,'orders':orders,
        'alerts':[],'outbox':[],'mqFailures':[],
        'ledgers':[{'initial':initial,'held':held,'activeOrders':held,
                    'dbAvailable':initial-held,'redisAvailable':initial-held,'inTransit':0,'pendingSend':0}]}


def evidence():
    counts={'register':8,'login':64,'captcha_image':32,'captcha_accessible':32,'token':64,
            'buy':64,'buy_replay':8,'order_status':64,'pay':48,'pay_replay':48}
    counts.update({k:4500 for k in ('catalog','catalog_filtered','detail','activity_info','orders','me')})
    api={k:{'count':n,'statuses':{'201' if k=='register' else '202' if k=='buy' else '200':n},
            'p50':10,'p95':20,'p99':30} for k,n in counts.items()}
    bursts=[]
    for stock in (64,32):
        statuses={'202':stock, **({'409':64-stock} if stock<64 else {})}
        bursts.append({'users':64,'initialStock':stock,'accepted':stock,'httpStatuses':statuses,
            'businessCodes':{'ACCEPTED':stock, **({'SOLD_OUT':64-stock} if stock<64 else {})},
            'buyApi':{'count':64,'statuses':statuses,'p50':50,'p95':200,'p99':300},
            'reconciliation':inventory(10+stock,stock,stock,stock)})
    return {'complete':True,'smokeOnly':False,'profile':{'durationSeconds':1800,'backgroundReadQps':15,
        'journeys':64,'naturalExpiryOrders':16,'paymentTtlMs':900000,'realRegistrations':8},
        'submissionSeconds':1800,'submittedReadRequests':27000,'completedJourneys':64,
        'durableObservedCount':64,'errors':[],'mixedApi':api,
        'durableOrderMs':{'p50':500,'p95':1000,'p99':1500},
        'naturalClosedObserved':16,'expiryToClosedObservedMs':{'p50':10000,'p95':20000,'p99':30000},
        'orderOutcomes':{'CLOSED':16,'PAID':48},'paymentRows':48,
        'requestCounts':{'rows':64,'distinctReservations':64,'distinctActivityUsers':64},
        'reconciliations':[inventory(i,64,16,n) for i,n in enumerate((22,21,21),1)],'bursts':bursts}


class JourneyGateTests(unittest.TestCase):
    def test_complete_profile_passes_without_summary_flag(self):
        self.assertTrue(evaluate(evidence())['passed'])

    def test_smoke_missing_and_unknown_request_cannot_pass(self):
        for field,value in [('smokeOnly',True),('submissionSeconds',120),('completedJourneys',63),
                            ('durableObservedCount',1),('naturalClosedObserved',15),('paymentRows',96),
                            ('mixedApi',{}),('errors',[{'error':'TimeoutError'}])]:
            with self.subTest(field=field):
                d=evidence();d[field]=value;d['passed']=True
                self.assertFalse(evaluate(d)['passed'])

    def test_changed_ttl_or_missing_image_flow_rejected(self):
        for change in [lambda d:d['profile'].update(paymentTtlMs=30000),
                       lambda d:d['mixedApi']['captcha_image'].update(count=0),
                       lambda d:d['mixedApi']['login'].update(statuses={'200':63,'429':1}),
                       lambda d:d['mixedApi']['detail'].update(p95=301,p99=400),
                       lambda d:d['expiryToClosedObservedMs'].update(p99=61000),
                       lambda d:d['durableOrderMs'].update(p95=float('nan'))]:
            d=evidence();change(d);self.assertFalse(evaluate(d)['passed'])

    def test_clean_label_cannot_hide_stock_or_payment_mismatch(self):
        for change in [lambda d:d['reconciliations'][0]['ledgers'][0].update(redisAvailable=49),
                       lambda d:d['requestCounts'].update(distinctReservations=63),
                       lambda d:d['bursts'][1].update(accepted=33),
                       lambda d:d['bursts'][1].update(httpStatuses={'202':32,'503':32}),
                       lambda d:d['bursts'][1]['reconciliation']['outbox'].append({'status':'PENDING'})]:
            d=evidence();change(d);self.assertFalse(evaluate(d)['passed'])

    def test_counter_aggregation_and_accessible_question_validation(self):
        self.assertEqual(accessible_answer('请计算 12 加 34，并输入得数。'),'46')
        with self.assertRaises(ValueError):accessible_answer('1+2; return 100')
        result=aggregate([{'route':'buy','status':202,'ms':10},{'route':'buy','status':0,'ms':20000}])
        self.assertEqual(result['buy']['statuses'],{'202':1,'0':1})
        self.assertEqual(result['buy']['p95'],20000)

    def test_cli_fails_closed_on_missing_or_malformed_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.json'
            for raw in ('[]','{}','not json','{"profile":null}'):
                path.write_text(raw,encoding='utf-8')
                result=subprocess.run([sys.executable,str(ROOT/'scripts/check_journey_gate.py'),str(path)],capture_output=True,text=True)
                self.assertEqual(result.returncode,1)
                self.assertFalse(json.loads(result.stdout)['passed'])


if __name__=='__main__':unittest.main()
