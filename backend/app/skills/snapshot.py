"""Immutable installed Skill catalogue/body for one Run, including workers."""
class SkillSnapshot:
    @classmethod
    async def capture(cls, store):
        instance = cls()
        instance.settings = store.settings
        instance._skills = {}
        instance.versions = {}
        from app.project_learning import skill_version
        for metadata in await store.catalog():
            for _ in range(3):
                try:
                    before = await store.load(metadata.name)
                    if before is None:
                        break
                    version = skill_version(before)
                    skill = await store.load(metadata.name)
                    if skill and skill.metadata.location == before.metadata.location and skill_version(skill) == version:
                        instance._skills[metadata.name] = skill
                        instance.versions[metadata.name] = version
                        break
                except (OSError, ValueError):
                    # Concurrent editing/disabling must not fail the new Run.
                    continue
        return instance

    async def catalog(self):
        return tuple(s.metadata for s in self._skills.values())

    async def load(self, name):
        return self._skills.get(name)
