"""Use the existing admission-fenced reader reload for this reader-only hotfix."""
from history_receipt import adapter


def load_base():
    base=adapter.load_base()
    restart=base.restart_for
    def reload_reader(manifest,admission_fence=None):
        # Coins evidence and its catalog/learning callers run in the FS reader.
        if manifest.get('scope')==adapter.SCOPE:
            return restart(dict(manifest,scope=base.HERMES_UPDATE_SCOPE),admission_fence)
        return restart(manifest,admission_fence)
    base.restart_for=reload_reader
    return base


if __name__=='__main__':load_base().main()
