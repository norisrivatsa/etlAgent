import random
from datetime import datetime, timedelta

import pandas as pd
from faker import Faker
from sqlalchemy import create_engine

fake = Faker()

# =====================================================
# CONFIG
# =====================================================

NUM_CUSTOMERS = 100000
NUM_MODELS = 25
NUM_MANUFACTURING_CYCLES = 100
NUM_ORDERS = 50000
NUM_SERVICES = 30000

DATABASE_URL = "postgresql://postgres:Barca%402210@localhost:5432/car_dealership"

# =====================================================
# DB CONNECTION
# =====================================================

engine = create_engine(DATABASE_URL)

# =====================================================
# CUSTOMERS
# =====================================================

customers = []

for customer_id in range(1, NUM_CUSTOMERS + 1):
    customers.append(
        {
            "customer_id": customer_id,
            "customer_name": fake.name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "address": fake.street_address(),
            "city": fake.city(),
            "created_at": fake.date_time_between(start_date="-3y", end_date="now"),
        }
    )

customers_df = pd.DataFrame(customers)

# =====================================================
# CAR MODELS
# =====================================================

brands = ["Toyota", "Honda", "Ford", "BMW", "Tesla"]

categories = ["Sedan", "SUV", "Hatchback", "Truck"]

fuel_types = ["Petrol", "Diesel", "Hybrid", "Electric"]

models = []

for model_id in range(1, NUM_MODELS + 1):
    brand = random.choice(brands)

    models.append(
        {
            "model_id": model_id,
            "model_name": f"{brand}_Model_{model_id}",
            "brand": brand,
            "category": random.choice(categories),
            "fuel_type": random.choice(fuel_types),
            "base_price": random.randint(15000, 90000),
        }
    )

models_df = pd.DataFrame(models)

# =====================================================
# MANUFACTURING CYCLES
# =====================================================

manufacturing = []

for cycle_id in range(1, NUM_MANUFACTURING_CYCLES + 1):
    model_id = random.randint(1, NUM_MODELS)

    start = fake.date_time_between(start_date="-2y", end_date="-6m")

    completion = start + timedelta(days=random.randint(15, 90))

    manufacturing.append(
        {
            "manufacturing_cycle_id": cycle_id,
            "model_id": model_id,
            "factory_name": random.choice(
                [
                    "Detroit Plant",
                    "Texas Plant",
                    "Berlin Gigafactory",
                    "Nagoya Plant",
                ]
            ),
            "batch_number": f"BATCH-{cycle_id}",
            "start_date": start,
            "completion_date": completion,
            "quality_score": round(
                random.uniform(80, 100),
                2,
            ),
        }
    )

manufacturing_df = pd.DataFrame(manufacturing)

# =====================================================
# ORDERS
# =====================================================

orders = []

for order_id in range(1, NUM_ORDERS + 1):
    customer_id = random.randint(1, NUM_CUSTOMERS)

    cycle_id = random.randint(1, NUM_MANUFACTURING_CYCLES)

    model_id = manufacturing_df.loc[
        manufacturing_df["manufacturing_cycle_id"] == cycle_id,
        "model_id",
    ].iloc[0]

    order_date = fake.date_time_between(start_date="-1y", end_date="now")

    delivery_date = order_date + timedelta(days=random.randint(5, 45))

    orders.append(
        {
            "order_id": order_id,
            "customer_id": customer_id,
            "model_id": model_id,
            "manufacturing_cycle_id": cycle_id,
            "order_date": order_date,
            "delivery_date": delivery_date,
            "order_status": random.choice(
                [
                    "Delivered",
                    "Pending",
                    "Cancelled",
                    "In Transit",
                ]
            ),
        }
    )

orders_df = pd.DataFrame(orders)

# =====================================================
# SERVICE RECORDS
# =====================================================

issues = [
    "Oil Change",
    "Brake Replacement",
    "Battery Issue",
    "Tire Rotation",
    "Engine Inspection",
]

services = []

for service_id in range(1, NUM_SERVICES + 1):
    order = orders_df.sample(1).iloc[0]

    services.append(
        {
            "service_id": service_id,
            "order_id": order.order_id,
            "customer_id": order.customer_id,
            "service_date": fake.date_time_between(
                start_date=order.order_date,
                end_date="now",
            ),
            "issue_reported": random.choice(issues),
            "cost": round(
                random.uniform(50, 3000),
                2,
            ),
        }
    )

services_df = pd.DataFrame(services)

# =====================================================
# WRITE TO DATABASE
# =====================================================

customers_df.to_sql(
    "customers",
    engine,
    if_exists="replace",
    index=False,
)

models_df.to_sql(
    "car_models",
    engine,
    if_exists="replace",
    index=False,
)

manufacturing_df.to_sql(
    "manufacturing_cycles",
    engine,
    if_exists="replace",
    index=False,
)

orders_df.to_sql(
    "orders",
    engine,
    if_exists="replace",
    index=False,
)

services_df.to_sql(
    "service_records",
    engine,
    if_exists="replace",
    index=False,
)

print("Data generated successfully")
