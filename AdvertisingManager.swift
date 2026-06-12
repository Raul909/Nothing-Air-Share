import Foundation
import Network

class AdvertisingManager: ObservableObject {
    private var listener: NWListener?
    private let serviceType = "_nothing-share._tcp"
    private let deviceName = "iOS Nothing Share" // In a real app, use UIDevice.current.name
    
    @Published var isAdvertising: Bool = false
    
    init() {
        startAdvertising()
    }
    
    func startAdvertising() {
        do {
            let parameters = NWParameters.tcp
            listener = try NWListener(using: parameters)
            
            listener?.service = NWListener.Service(name: deviceName, type: serviceType)
            
            listener?.stateUpdateHandler = { [weak self] state in
                DispatchQueue.main.async {
                    switch state {
                    case .ready:
                        self?.isAdvertising = true
                        print("Advertising Manager: Ready and advertising as \(self?.deviceName ?? "unknown")")
                    case .failed(let error):
                        self?.isAdvertising = false
                        print("Advertising Manager: Failed with error: \(error)")
                    default:
                        break
                    }
                }
            }
            
            listener?.newConnectionHandler = { connection in
                // Hand off to TransferManager's Receiver
                print("Advertising Manager: Received new connection from \(connection.endpoint)")
                connection.cancel() // Placeholder: for now we just want to be visible
            }
            
            listener?.start(queue: .main)
            
        } catch {
            print("Advertising Manager: Failed to initialize listener: \(error)")
        }
    }
    
    func stopAdvertising() {
        listener?.cancel()
        listener = nil
        isAdvertising = false
    }
}
