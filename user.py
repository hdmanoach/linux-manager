import os
import subprocess

def menu():
    print("Menu de gestion de creation d'utilisateurs et de groupes sur Linux")
    print("1. Creation d'un utilisateur")
    print("2. Creation d'un groupe")
    print("3. Ajouter un utilisateur a un groupe")
    print("4. Supprimer un utilisateur d'un groupe")
    print("5. Supprimer un groupe")
    print("6. Supprimer un utilisateur")
    print("7. Afficher les groupes d'un utilisateur")
    print("8. Afficher les utilisateurs d'un groupe")
    print("9. Afficher les utilisateurs du systeme")
    print("10.lister les groupes du systeme")
    print("11. Lister les utilisateurs connectes au systeme")
    print("12. Quitter")
    print("Veuillez choisir une option : ")



def create_user():
    print("Creation d'un utilisateur")
    nb_users = input("Entrez le nombre d'utilisateurs a créer : ")
    for i in range(int(nb_users)):
        username = input("Nom d'utilisateur : ")
        #password = input("Mot de passe : ")
        subprocess.run(["useradd", username])
        #print(f"Creation de l'utilisateur {username} avec le mot de passe {password}")

def create_group():
    print("Creation d'un groupe")

def add_user_to_group():
    print("Ajouter un utilisateur a un groupe")

def remove_user_from_group():
    print("Supprimer un utilisateur d'un groupe")

def remove_group():
    print("Supprimer un groupe")

def remove_user():
    print("Supprimer un utilisateur")

def show_user_groups():
    print("Afficher les groupes d'un utilisateur")

def show_group_users():
    print("Afficher les utilisateurs d'un groupe")

def show_users():
    print("Afficher les utilisateurs du systeme")

def show_groups():
    print("lister les groupes du systeme")

def show_connected_users():
    print("lister les utilisateurs connectes au systeme")

def quit():
    print("Quitter")

if __name__ == "__main__":
    menu()
    choice = int(input())

    if choice == 1:
        print("Creation d'un utilisateur")
    elif choice == 2:
        print("Creation d'un groupe")
    elif choice == 3:
        print("Ajouter un utilisateur a un groupe")
    elif choice == 4:
        print("Supprimer un utilisateur d'un groupe")
    elif choice == 5:
        print("Supprimer un groupe")
    elif choice == 6:
        print("Supprimer un utilisateur")
    elif choice == 7:
        print("Afficher les groupes d'un utilisateur")
    elif choice == 8:
        print("Afficher les utilisateurs d'un groupe")
    elif choice == 9:
        print("Afficher les utilisateurs du systeme")
    elif choice == 10:
        print("lister les groupes du systeme")
    elif choice == 11:
        print("lister les utilisateurs connectes au systeme")
    elif choice == 12:
        print("Quitter")