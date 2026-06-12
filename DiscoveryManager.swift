import Foundation
import Network

struct DiscoveredDevice: Identifiable, Hashable {
    let id: UUID = UUID()
    let name: String
    let endpoint: NWEndpoint
    var lastSeen: Date = Date()
    
    // Extract IP/Port if possible for UI
    var connectionString: String {
        if case let .hostPort(host, port) = endpoint {
            return "\(host):\(port)"
        }
        return "Resolving..."
    }
}

class DiscoveryManager: ObservableObject {
    @Published var discoveredDevices: [DiscoveredDevice] = []
    
    private var browser: NWBrowser?
    private let serviceType = "_nothing-share._tcp"
    private let domain = "local."
    
    init() {
        startBrowsing()
    }
    
    func startBrowsing() {
        let parameters = NWParameters()
        parameters.includePeerToPeer = true
        
        let descriptor = NWBrowser.Descriptor.bonjour(type: serviceType, domain: domain)
        browser = NWBrowser(for: descriptor, using: .main)
        
        browser?.stateUpdateHandler = { state in
            switch state {
            case .ready:
                print("Discovery Manager: Ready and browsing...")
            case .failed(let error):
                print("Discovery Manager: Failed with error: \(error)")
            default:
                break
            }
        }
        
        browser?.browseResultsChangedHandler = { [weak self] results, changes in
            guard let self = self else { return }
            
            var newDevices: [DiscoveredDevice] = []
            for result in results {
                if case let .bonjourService(name, type, domain, txtRecord) = result.endpoint {
                    // In a real app, we'd parse the TXT record for device details
                    let device = DiscoveredDevice(name: name, endpoint: result.endpoint)
                    newDevices.append(device)
                }
            }
            
            DispatchQueue.main.async {
                self.discoveredDevices = newDevices
            }
        }
        
        browser?.start(queue: .main)
    }
    
    func stopBrowsing() {
        browser?.cancel()
        browser = nil
    }
}
