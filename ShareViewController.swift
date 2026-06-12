import UIKit
import Social
import SwiftUI
import UniformTypeIdentifiers

class ShareViewController: UIViewController {
    
    override func viewDidLoad() {
        super.viewDidLoad()
        
        // 1. Extract the shared item (file/photo)
        guard let extensionItem = extensionContext?.inputItems.first as? NSExtensionItem,
              let attachment = extensionItem.attachments?.first else {
            self.extensionContext?.completeRequest(returningItems: [], completionHandler: nil)
            return
        }
        
        // 2. Load the item and show the SwiftUI View
        let contentType = UTType.data.identifier
        if attachment.hasItemConformingToTypeIdentifier(contentType) {
            attachment.loadItem(forTypeIdentifier: contentType, options: nil) { [weak self] (data, error) in
                guard let self = self else { return }
                
                var fileURL: URL?
                if let url = data as? URL {
                    fileURL = url
                }
                
                DispatchQueue.main.async {
                    self.setupSwiftUI(with: fileURL)
                }
            }
        }
    }
    
    private func setupSwiftUI(with fileURL: URL?) {
        let shareView = ShareView(fileURL: fileURL) { [weak self] in
            // Completion handler to close the extension
            self?.extensionContext?.completeRequest(returningItems: [], completionHandler: nil)
        }
        
        let hostingController = UIHostingController(rootView: shareView)
        addChild(hostingController)
        view.addSubview(hostingController.view)
        hostingController.view.translatesAutoresizingMaskIntoConstraints = false
        
        NSLayoutConstraint.activate([
            hostingController.view.topAnchor.constraint(equalTo: view.topAnchor),
            hostingController.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            hostingController.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            hostingController.view.trailingAnchor.constraint(equalTo: view.trailingAnchor)
        ])
        
        hostingController.didMove(toParent: self)
    }
}
