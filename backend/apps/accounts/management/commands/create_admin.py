from getpass import getpass

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Create the first MT Rotator administrator"

    def add_arguments(self, parser):
        parser.add_argument("--email")
        parser.add_argument("--display-name", default="管理员")

    def handle(self, *args, **options):
        email = options["email"] or input("Email: ").strip()
        if User.objects.filter(email=email.casefold()).exists():
            raise CommandError("该邮箱已经存在")
        password = getpass("Password: ")
        confirmation = getpass("Confirm password: ")
        if password != confirmation:
            raise CommandError("两次密码不一致")
        User.objects.create_superuser(email=email, password=password, display_name=options["display_name"])
        self.stdout.write(self.style.SUCCESS(f"Created administrator {email}"))
