import os, sys
import logging
import time
import smtplib
from email.mime.text import MIMEText

import boto
import boto.ec2

logging.getLogger('boto').setLevel(logging.CRITICAL)
CWD = os.path.dirname(os.path.abspath(__file__))

LOG_FORMAT = '%(asctime)s %(levelname)s: %(message)s'
logging.basicConfig(format=LOG_FORMAT)
logger = logging.getLogger('monitor')
formatter = logging.Formatter(LOG_FORMAT)
handler = logging.handlers.RotatingFileHandler(os.path.join(CWD,'splunk_monitor.log'), maxBytes=10**6, backupCount=3)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def email(instance_id):
    s = smtplib.SMTP('10.20.7.132')
    msg = MIMEText("""rebooting %s""" % (instance_id))
    sender = 'autofix@crowdstrike.com'
    recipients = ['mike.schon@crowdstrike.com', 'evan.bullock-morales@crowdstrike.com']
    msg['Subject'] = "rebooting %s" % (instance_id)
    msg['From'] = sender
    msg['To'] = ", ".join(recipients)
    s.sendmail(sender, recipients, msg.as_string())


def get_instances(conn, **args):
    """ returns instance objects """
    logger.debug('get_instances')
    try:
        results = conn.get_all_reservations(**args)
    except boto.exception.EC2ResponseError, e:
        results = []

    return [inst for res in results for inst in res.instances]


def get_status(conn, **args):
    logger.debug('get_status')
    try:
        results = conn.get_all_instance_status(**args)
    except boto.exception.EC2ResponseError, e:
        results = []

    return results

def main():
    conn = boto.ec2.connect_to_region('us-west-1') # Prod
    #conn = boto.ec2.connect_to_region('us-east-1') # Dev
    logger.info('getting statuses')
    instance_impaired = get_status(conn, filters={'instance-status.status': 'impaired'})
    system_impaired = get_status(conn, filters={'system-status.status': 'impaired'})
    reachability_impaired = get_status(conn, filters={'system-status.reachability': 'failed'})

    all_impaired = list(set(instance_impaired) | set(system_impaired) | set(reachability_impaired))
    if not len(all_impaired):
        sys.exit()

    all_impaired = get_instances(conn, instance_ids=[i.id for i in all_impaired])

    splunk_impaired = [i for i in all_impaired if i.tags['SecurityGroups'] == 'splunk-customer-server'] # Prod
    # splunk_impaired = [i for i in all_impaired if i.tags['SecurityGroups'] == 'splunk-customer'] # Dev
    logger.info('Splunk Impaired: %s' % ', '.join([i.id for i in splunk_impaired]))

    for i in splunk_impaired:
        email(i.id)
        if i.root_device_type != 'ebs':
            logger.error('cannot reboot %s due to instance store root device' % i)
            continue
        logger.info('rebooting %s' % i)
        i.stop(force=True)
        time.sleep(5)
        while i.state != 'stopped':
            logger.info('state: %s' % i.state)
            time.sleep(5)
            i.update()
        logger.info('starting %s' % i)
        i.start()



if __name__ == '__main__':
    main()
