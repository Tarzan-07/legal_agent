"""
RabbitMQ Background Worker Processing Daemon.
Listens to queue events, pulls files down from storage, and executes pipelines.
"""

import os
import pika
import logging
import tempfile
import json
from supabase import Client, create_client

from doc_tools import process_and_graph_doc

logging.basicConfig(logging.INFO)
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
BUCKET_NAME = os.getenv('BUCKET_NAME')
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'localhost')
QUEUE_NAME = 'invoice_processing_queue'

supabase: Client = create_client(supabase_url=SUPABASE_URL, supabase_key=SUPABASE_KEY)

def callback(ch, method, properties, body):
    """Fires automatically whenever a fresh message object arrives on the broker bus."""
    temp_local_path = None
    task_data = json.loads(body.decode('utf-8'))

    file_path = task_data['file_path']
    original_filename = task_data['original_filename']

    logger.info(f"Received task to process: {original_filename}")

    try:
        file_bytes = supabase.storage.from_(BUCKET_NAME).download(file_path)

        file_suffix = os.path.splitext(original_filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_suffix) as temp_file:
            temp_file.write(file_bytes)
            temp_local_path = temp_file.name

        logger.info(f"Processing structural extraction via AI layers for: {original_filename}")
        process_and_graph_doc(temp_local_path, original_filename)

        ch.basic_ack(delivery_tag=method.delivery_tag)
        logger.info(f"Task completed successfully and acknowledged: {original_filename}")
    
    except Exception as e:
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
    finally:
        if temp_local_path and os.path.exists(temp_local_path):
            os.remove(temp_local_path)


def start_worker():
    """Main execution block managing blocking connection channels on message broker loops."""
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
    channel = connection.channel()

    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)
    logger.info("Background processing worker engine initialized. Awaiting invoice tasks...")

    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        logger.info("Stopping background processing workers cleanly...")
        channel.stop_consuming()

    finally:
        connection.close()

if __name__=='__main__':
    start_worker()