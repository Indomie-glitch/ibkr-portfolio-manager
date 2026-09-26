from ib_async import IB

# 127.0.0.1 = your own machine, 4002 = paper trading port
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)

print("Connected:", ib.isConnected())

positions = ib.positions()

if not positions:
    print("No positions found (empty paper account, or not connected properly)")
else:
    for pos in positions:
        print(f"{pos.contract.symbol}: {pos.position} shares @ avg cost {pos.avgCost}")

ib.disconnect()