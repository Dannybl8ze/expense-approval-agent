import time

def get_user_data(users, id):
   # Find user by ID
   for u in users:
       if u['id'] == id:
            return u
   return None

def process_payments(items):
   total = 0
   for i in items:
       # Calculate tax
       tax = i['price'] * 0.1
       total = total + i['price'] + tax
       time.sleep(0.1) # Simulate slow network call
  
   return total

def run_batch():
   users = [{'id': 1, 'name': 'Alice'}, {'id': 2, 'name': 'Bob'}]
   items = [{'price': 10}, {'price': 20}, {'price': 100}]
  
   u = get_user_data(users, 3)
   print("User found: " + u['name']) # Will crash if None
  
   print("Total: " + str(process_payments(items)))

if __name__ == "__main__":
   run_batch()